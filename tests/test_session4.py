"""Session 4 tests — replies. Fake Sheet, fake WhatsApp, fake email, fake Groq."""
from datetime import datetime

import pytest

import config
from nodes.classifier import classify_reply, rule_classify
from nodes.reply import handle_incoming, parse_meta_payload
from sheets import row_to_record

DEMO_NO = "+923183355708"


class FakeSheets:
    def __init__(self, rows, log=None):
        self.rows, self.log, self.hot = [dict(r) for r in rows], [list(x) for x in (log or [])], []

    def get_queue(self):
        return [row_to_record({h: str(r.get(k, "")) for k, h in config.QUEUE_COLUMNS}, i + 2)
                for i, r in enumerate(self.rows)]

    def log_rows(self):
        return self.log

    def update_queue_cells(self, row, updates):
        self.rows[row - 2].update(updates)

    def append_log_row(self, values):
        self.log.append([str(v) for v in values])

    def append_hot_row(self, values):
        self.hot.append(values)


def lead(i, **kw):
    return {"lead_id": f"NB-{i}", "name": f"Ahmed{i} Al-Rashid", "company": "Dubai Laundry",
            "phone": f"+97150000000{i}", "industry": "Hotel", "product_interest": "Terry towels",
            "market": "Gulf", "original_score": 65, "nurture_start_date": "2026-09-27",
            "last_contacted": "2026-09-30", "messages_sent": 1, "day_number": 7,
            "next_followup_date": "2026-10-04", "status": "nurturing", "notes": "DEMO"} | kw


def sent_log(lead_id, wamid):
    return ["2026-09-30 04:40", lead_id, "x", "3", "msg", "No", "", "", "SENT (demo) -> +92", wamid]


def payload(text, frm=DEMO_NO, context=None, mid="wamid.IN1"):
    m = {"from": frm.lstrip("+"), "id": mid, "type": "text", "text": {"body": text}}
    if context:
        m["context"] = {"id": context}
    return {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": frm.lstrip("+"),
                                                             "profile": {"name": "X"}}],
                                               "messages": [m]}}]}]}


class Recorder:
    def __init__(self):
        self.wa, self.email = [], []

    def text(self, to, body):
        self.wa.append((to, body))
        return "wamid.OUT"

    def mail(self, to, subject, body):
        self.email.append((to, subject, body))
        return "ok"


def llm_says(label, conf=0.9):
    return lambda system, user: f'{{"classification": "{label}", "confidence": {conf}, ' \
                                f'"reasoning": "test", "signals": []}}'


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(config, "ALERT_EMAIL", "junaid@test.com")
    monkeypatch.setattr(config, "ALERT_WA_NUMBER", DEMO_NO)
    monkeypatch.setattr(config, "DEMO_WA_NUMBER", DEMO_NO)
    monkeypatch.setattr(config, "AUTO_ACK", True)
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 9, 30, 10, 0, tzinfo=config.TZ))


def run(sheets, rec, p, llm=None, demo=True):
    return handle_incoming(p, sheets, llm, {"text": rec.text}, rec.mail, demo_mode=demo)


# ── Classifier ─────────────────────────────────────────────────
@pytest.mark.parametrize("text,label", [
    ("Yes interested, need 500 pieces", "HOT"),
    ("can we do a call tomorrow?", "HOT"),
    ("please send your catalogue", "HOT"),
    ("need 2 containers before Ramadan", "HOT"),
    ("stop", "STOP"), ("Please remove me from this list", "STOP"),
    ("not interested thanks", "STOP"), ("mujhe messages mat bhejo", "STOP"),
    ("ok thanks", "WARM"), ("what are your prices?", "WARM"),
])
def test_rules(text, label):
    assert rule_classify(text)["classification"] == label


def test_stop_rules_beat_llm():
    v = classify_reply("stop messaging me, we need 500 pcs from someone else", llm=llm_says("HOT"))
    assert v["classification"] == "STOP" and v["source"] == "rules"


def test_llm_can_downgrade_false_hot():
    v = classify_reply("we don't need 500 pieces right now", llm=llm_says("WARM"))
    assert v["classification"] == "WARM" and v["source"] == "llm"


def test_llm_failure_falls_back_to_rules():
    def broken(s, u):
        raise TimeoutError
    v = classify_reply("need 500 pieces next month", llm=broken)
    assert v["classification"] == "HOT" and v["source"] == "rules"
    assert classify_reply("hello", llm=lambda s, u: "not json")["source"] == "rules"


# ── Parsing ────────────────────────────────────────────────────
def test_parse_payload_with_context_and_status():
    p = payload("hi", context="wamid.A")
    p["entry"][0]["changes"][0]["value"]["statuses"] = [
        {"id": "wamid.B", "status": "failed", "errors": [{"code": 131047, "title": "Re-engagement"}]}]
    out = parse_meta_payload(p)
    assert out["messages"][0]["context_id"] == "wamid.A" and out["messages"][0]["from"] == DEMO_NO
    assert out["statuses"][0]["error_code"] == 131047


# ── Full flow ──────────────────────────────────────────────────
def test_demo_hot_reply_via_reply_to():
    sh, rec = FakeSheets([lead(1), lead(2)], [sent_log("NB-2", "wamid.S2")]), Recorder()
    out = run(sh, rec, payload("Yes interested, need 500 pieces", context="wamid.S2"),
              llm=llm_says("HOT"))
    r = out["results"][0]
    assert out["handled"] and r["lead_id"] == "NB-2" and r["classification"] == "HOT"
    assert sh.rows[1]["status"] == "HOT" and sh.rows[0]["status"] == "nurturing"
    assert len(sh.hot) == 1 and sh.hot[0][1] == "NB-2"
    assert rec.email and "HOT lead" in rec.email[0][1]
    assert any("Thank you" in b for _, b in rec.wa)             # thank-you to lead
    assert sh.log[-1][5] == "Yes" and sh.log[-1][7] == "HOT" and sh.log[-1][9] == "wamid.IN1"


def test_demo_plain_hi_without_reply_to_is_not_handled():
    sh, rec = FakeSheets([lead(1)], [sent_log("NB-1", "wamid.S1")]), Recorder()
    out = run(sh, rec, payload("Hi"))
    assert out["handled"] is False and rec.wa == [] and len(sh.log) == 1


def test_stop_opts_out_and_confirms():
    sh, rec = FakeSheets([lead(1)], [sent_log("NB-1", "wamid.S1")]), Recorder()
    run(sh, rec, payload("stop", context="wamid.S1"))
    assert sh.rows[0]["status"] == "opted_out"
    assert any("won't receive" in b for _, b in rec.wa)


def test_warm_continues_sequence():
    sh, rec = FakeSheets([lead(1)], [sent_log("NB-1", "wamid.S1")]), Recorder()
    out = run(sh, rec, payload("thanks, what are your prices?", context="wamid.S1"),
              llm=llm_says("WARM"))
    assert out["results"][0]["classification"] == "WARM"
    assert sh.rows[0]["status"] == "nurturing" and rec.email == []


def test_meta_retry_processed_once():
    sh, rec = FakeSheets([lead(1)], [sent_log("NB-1", "wamid.S1")]), Recorder()
    p = payload("need 500 pieces", context="wamid.S1")
    run(sh, rec, p, llm=llm_says("HOT"))
    out2 = run(sh, rec, p, llm=llm_says("HOT"))
    assert out2["results"][0].get("duplicate") and len(rec.email) == 1 and len(sh.hot) == 1


def test_live_mode_matches_by_phone():
    sh, rec = FakeSheets([lead(1), lead(2)]), Recorder()
    out = run(sh, rec, payload("send catalogue please", frm="+971500000002"),
              llm=llm_says("HOT"), demo=False)
    assert out["results"][0]["lead_id"] == "NB-2"
    assert rec.wa[-1][0] == "+971500000002"                   # thank-you goes to the lead


def test_unknown_number_passes_to_next_agent():
    sh, rec = FakeSheets([lead(1)]), Recorder()
    out = run(sh, rec, payload("hello", frm="+15550001111"), demo=False)
    assert out["handled"] is False


def test_opted_out_lead_is_ignored():
    sh, rec = FakeSheets([lead(1, status="opted_out")], [sent_log("NB-1", "wamid.S1")]), Recorder()
    out = run(sh, rec, payload("need 500 pcs", context="wamid.S1"), llm=llm_says("HOT"))
    assert out["results"][0]["classification"] == "IGNORED" and rec.wa == [] and rec.email == []


def test_already_hot_lead_alerts_again_without_duplicate_row():
    sh, rec = FakeSheets([lead(1, status="HOT")], [sent_log("NB-1", "wamid.S1")]), Recorder()
    run(sh, rec, payload("when can you call?", context="wamid.S1"), llm=llm_says("HOT"))
    assert sh.hot == [] and len(rec.email) == 1


def test_delivery_failure_logged():
    sh, rec = FakeSheets([lead(1)], [sent_log("NB-1", "wamid.S1")]), Recorder()
    p = {"entry": [{"changes": [{"value": {"statuses": [
        {"id": "wamid.S1", "status": "failed", "errors": [{"code": 131047, "title": "Re-engagement"}]}]}}]}]}
    out = run(sh, rec, p)
    assert out["delivery_failures"][0]["lead_id"] == "NB-1"
    assert "DELIVERY FAILED" in sh.log[-1][8]
