"""Session 1 tests — no Google account needed (in-memory fake sheet).
Run: pytest -q
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import config
import main
from nodes.intake import normalize_phone
from nodes.scheduler import find_due_leads
from sheets import row_to_record


class FakeSheets:
    def __init__(self):
        self.rows = []

    def ensure_structure(self):
        return ["fake"]

    def get_queue(self):
        return [row_to_record({h: str(r.get(k, "")) for k, h in config.QUEUE_COLUMNS}, i + 2)
                for i, r in enumerate(self.rows)]

    def append_queue_row(self, record):
        self.rows.append(dict(record))

    def count_messages_on(self, day):
        return 0

    def count_hot_upgrades(self):
        return 0


@pytest.fixture
def fake():
    return FakeSheets()


@pytest.fixture
def client(fake, monkeypatch):
    main.app.dependency_overrides[main.get_sheets] = lambda: fake
    monkeypatch.setattr(main, "get_sheets", lambda: fake)   # /health calls it directly
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


LEAD = dict(name="Ahmed", company="Dubai Laundry", phone="+971 50 000 0001",
            industry="Hotel supplies", product_interest="Towels", market="UAE",
            original_score=65)


def test_phone_normalization():
    assert normalize_phone("0318-3355708") == "+923183355708"
    assert normalize_phone("00971500000001") == "+971500000001"
    assert normalize_phone("+49 150 000 0003") == "+491500000003"
    with pytest.raises(ValueError):
        normalize_phone("12ab")


def test_add_lead_sets_day3(client, fake):
    r = client.post("/add-lead", json=LEAD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["day_number"] == 3
    assert body["first_followup"] == (config.today() + timedelta(days=3)).isoformat()
    row = fake.rows[0]
    assert row["phone"] == "+971500000001" and row["market"] == "Gulf"
    assert row["status"] == "nurturing" and row["messages_sent"] == 0


def test_duplicate_rejected(client):
    assert client.post("/add-lead", json=LEAD).status_code == 200
    assert client.post("/add-lead", json=LEAD).status_code == 409


def test_opted_out_never_readded(client, fake):
    client.post("/add-lead", json=LEAD)
    fake.rows[0]["status"] = "opted_out"
    assert client.post("/add-lead", json=LEAD).status_code == 409


def test_archived_can_be_renurtured(client, fake):
    client.post("/add-lead", json=LEAD)
    fake.rows[0]["status"] = "archived"
    assert client.post("/add-lead", json=LEAD).status_code == 200


def test_validation_error(client):
    assert client.post("/add-lead", json=LEAD | {"original_score": 150}).status_code == 422


def test_demo_backdate_is_due_today(client):
    for day in (3, 7, 14):
        r = client.post("/add-lead", json=LEAD | {"phone": f"+97150000{day:04d}", "start_at_day": day})
        assert r.status_code == 200, r.text
    r = client.get("/due-today").json()
    assert r["count"] == 3
    by_day = sorted(r["due_leads"], key=lambda l: l["day_number"])
    assert [l["day_number"] for l in by_day] == [3, 7, 14]
    assert [l["messages_sent"] for l in by_day] == [0, 1, 2]


def test_future_date_simulation(client):
    client.post("/add-lead", json=LEAD)
    assert client.get("/due-today").json()["count"] == 0
    in3 = (config.today() + timedelta(days=3)).isoformat()
    assert client.get(f"/due-today?run_date={in3}").json()["count"] == 1


def test_scheduler_rules():
    t = date(2026, 10, 1)
    base = dict(name="x", messages_sent=0, _row=2, status="nurturing")
    queue = [
        base | {"lead_id": "A", "next_followup_date": "2026-10-01"},                 # due
        base | {"lead_id": "B", "next_followup_date": "2026-09-29"},                 # overdue → due
        base | {"lead_id": "C", "next_followup_date": "2026-10-04"},                 # future
        base | {"lead_id": "D", "next_followup_date": "2026-10-01", "status": "HOT"},
        base | {"lead_id": "E", "next_followup_date": "garbage"},
        base | {"lead_id": "F", "next_followup_date": "2026-10-01", "messages_sent": 5},
    ]
    due, warnings = find_due_leads(queue, t)
    assert [l["lead_id"] for l in due] == ["B", "A"]
    assert due[0]["overdue_days"] == 2
    assert len(warnings) == 2


def test_next_sequence_day():
    assert [config.next_sequence_day(d) for d in config.SEQUENCE_DAYS] == [7, 14, 21, 30, None]


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "running" and r["leads_in_queue"] == 0
