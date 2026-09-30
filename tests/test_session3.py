"""Session 3 tests — fake Sheet + fake WhatsApp, nothing is really sent."""
from datetime import date, datetime, timedelta

import pytest

import config
import nodes.sender as sender_mod
from graph import run_daily
from nodes.generator import clean_output
from nodes.sender import SendSettings, to_template_params
from nodes.updater import compute_updates
from sheets import row_to_record

TODAY = config.today()


class FakeSheets:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.log = []

    def get_queue(self):
        return [row_to_record({h: str(r.get(k, "")) for k, h in config.QUEUE_COLUMNS}, i + 2)
                for i, r in enumerate(self.rows)]

    def update_queue_cells(self, row, updates):
        self.rows[row - 2].update(updates)

    def append_log_row(self, values):
        self.log.append(values)


def lead(i, day, **kw):
    start = TODAY - timedelta(days=day)
    return {"lead_id": f"NB-{i}", "name": f"Lead{i} Test", "company": "Co", "phone": f"+97150000000{i}",
            "industry": "Hotel supplies", "product_interest": "Terry towels", "market": "Gulf",
            "original_score": 60, "nurture_start_date": start.isoformat(), "last_contacted": "",
            "messages_sent": [3, 7, 14, 21, 30].index(day), "day_number": day,
            "next_followup_date": TODAY.isoformat(), "status": "nurturing", "notes": "DEMO"} | kw


class FakeWA:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def text(self, to, body):
        if len(self.sent) in self.fail_for:
            self.sent.append(None)
            raise RuntimeError("WhatsApp 400 (code 131047): outside 24h")
        self.sent.append(("text", to, body))
        return f"wamid.{len(self.sent)}"

    def template(self, to, name, lang, params):
        self.sent.append(("template", to, name, params))
        return f"wamid.{len(self.sent)}"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sender_mod, "SLEEP", lambda s: None)
    monkeypatch.setattr(config, "now", lambda: datetime.now(config.TZ).replace(hour=10))


DEMO = SendSettings(demo_mode=True, demo_wa="+923183355708", delay_seconds=0, max_per_run=20)


def run(sheets, wa, settings=DEMO, dry=False):
    return run_daily(sheets, None, {"text": wa.text, "template": wa.template},
                     settings=settings, dry_run=dry)


def test_demo_run_sends_all_to_demo_number_and_updates_sheet():
    sh, wa = FakeSheets([lead(1, 3), lead(2, 7), lead(3, 14)]), FakeWA()
    out = run(sh, wa)
    assert out["sent"] == 3 and out["failed"] == 0
    assert all(s[1] == "+923183355708" for s in wa.sent)          # never to the lead
    r1 = sh.rows[0]
    assert r1["day_number"] == 7 and r1["messages_sent"] == 1 and r1["last_contacted"] == TODAY.isoformat()
    assert r1["next_followup_date"] == (TODAY + timedelta(days=4)).isoformat()   # start+7
    assert len(sh.log) == 3 and sh.log[0][8].startswith("SENT (demo)")


def test_second_run_same_day_sends_nothing():
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()
    run(sh, wa)
    out = run(sh, wa)
    assert out["due"] == 0 and len(wa.sent) == 1


def test_dry_run_changes_nothing():
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()
    out = run(sh, wa, dry=True)
    assert out["would_send"] == 1 and wa.sent == [] and sh.log == []
    assert sh.rows[0]["day_number"] == 3


def test_failure_is_logged_and_retried_next_run():
    sh, wa = FakeSheets([lead(1, 3), lead(2, 7)]), FakeWA(fail_for={0})
    out = run(sh, wa)
    assert out["failed"] == 1 and out["sent"] == 1
    assert "131047" in sh.log[0][8]
    assert sh.rows[0]["day_number"] == 3            # not advanced → still due


def test_status_rechecked_right_before_sending():
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()

    original = sh.get_queue
    calls = {"n": 0}
    def queue_then_opt_out():
        calls["n"] += 1
        if calls["n"] == 2:                          # scheduler read = 1, sender re-read = 2
            sh.rows[0]["status"] = "opted_out"
        return original()
    sh.get_queue = queue_then_opt_out
    out = run(sh, wa)
    assert out["skipped"] == 1 and wa.sent == []


def test_day30_archives_with_monthly_recheck():
    upd = compute_updates(lead(1, 30), TODAY)
    assert upd["status"] == "archived" and upd["messages_sent"] == 5
    assert upd["next_followup_date"] == (TODAY + timedelta(days=30)).isoformat()


def test_late_send_keeps_minimum_gap():
    late = lead(1, 3, nurture_start_date=(TODAY - timedelta(days=10)).isoformat())
    upd = compute_updates(late, TODAY)               # start+7 is in the past
    assert upd["next_followup_date"] == (TODAY + timedelta(days=3)).isoformat()


def test_live_mode_uses_template_and_real_number():
    live = SendSettings(demo_mode=False, delay_seconds=0, mode="template",
                        template_name="nurture_followup", template_lang="en")
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()
    out = run(sh, wa, settings=live)
    assert out["sent"] == 1
    kind, to, name, params = wa.sent[0]
    assert kind == "template" and to == "+971500000001" and name == "nurture_followup"
    assert "\n" not in params[1]


def test_live_mode_without_template_fails_safely():
    live = SendSettings(demo_mode=False, delay_seconds=0, mode="template", template_name="")
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()
    out = run(sh, wa, settings=live)
    assert out["failed"] == 1 and "WA_NURTURE_TEMPLATE" in out["results"][0]["detail"]


def test_live_mode_blocked_outside_business_hours(monkeypatch):
    monkeypatch.setattr(config, "now", lambda: datetime.now(config.TZ).replace(hour=22))
    live = SendSettings(demo_mode=False, delay_seconds=0, template_name="t")
    sh, wa = FakeSheets([lead(1, 3)]), FakeWA()
    out = run(sh, wa, settings=live)
    assert out["sent"] == 0 and "business hours" in out["note"]


def test_max_per_run():
    s = SendSettings(demo_mode=True, demo_wa="+92300", delay_seconds=0, max_per_run=2)
    sh, wa = FakeSheets([lead(i, 3) for i in range(1, 6)]), FakeWA()
    out = run(sh, wa, settings=s)
    assert out["sent"] == 2 and "3 more" in out["note"]


def test_template_params_drop_greeting_and_newlines():
    p = to_template_params("Ahmed", "Salam Ahmed,\n\nHope all good.\nQuick share.")
    assert p == ["Ahmed", "Hope all good. Quick share."]


def test_unicode_hyphens_cleaned():
    assert clean_output("hotel\u2011grade 15\u2011minute") == "hotel-grade 15-minute"
