"""Session 5 tests — security, reply-day fix, dashboard data."""
import hashlib
import hmac
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import config
import main
from nodes.reply import replied_day
from streamlit_app.data import counters, log_table, queue_table


@pytest.fixture
def client():
    main.app.dependency_overrides[main.get_llm] = lambda: None
    main.app.dependency_overrides[main.get_json_llm] = lambda: None
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


LEAD = {"lead": {"name": "Sarah Khan", "phone": "+491500000003", "industry": "Fashion",
                 "product_interest": "Knitwear", "market": "EU", "day_number": 14}}


def test_no_key_needed_locally(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    assert client.post("/nurture", json=LEAD).status_code == 200


def test_key_required_on_render(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "s3cret")
    assert client.post("/nurture", json=LEAD).status_code == 401
    assert client.post("/nurture", json=LEAD, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/nurture", json=LEAD, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.post("/run-daily").status_code == 401
    assert client.get("/ping").status_code == 200                 # health check stays open


def test_webhook_rejects_unsigned_when_secret_set(client, monkeypatch):
    monkeypatch.setattr(config, "WA_APP_SECRET", "appsecret")
    main.app.dependency_overrides[main.get_sheets] = lambda: None
    assert client.post("/webhook", content=b'{"entry": []}').status_code == 401


def test_webhook_accepts_valid_meta_signature(client, monkeypatch):
    monkeypatch.setattr(config, "WA_APP_SECRET", "appsecret")

    class EmptySheets:
        def log_rows(self): return []
        def get_queue(self): return []

    main.app.dependency_overrides[main.get_sheets] = lambda: EmptySheets()
    main.app.dependency_overrides[main.get_senders] = lambda: {}
    main.app.dependency_overrides[main.get_email_sender] = lambda: None
    body = json.dumps({"entry": []}).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and r.json()["handled"] is False


def test_webhook_verify(client, monkeypatch):
    monkeypatch.setattr(config, "WA_VERIFY_TOKEN", "tok")
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok",
                                        "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                          "hub.challenge": "1"}).status_code == 403


def test_replied_day_uses_message_answered_not_next_day():
    log = [["d", "NB-1", "Ahmed", "3", "msg", "No", "", "", "SENT (demo)", "wamid.S3"]]
    lead = {"lead_id": "NB-1", "day_number": 7}
    assert replied_day(log, lead, "wamid.S3") == 3              # reply-to
    assert replied_day(log, lead, None) == 3                     # last sent
    assert replied_day([], lead, None) == 7                      # nothing logged


Q = [{"name": "A", "company": "c", "product_interest": "p", "market": "Gulf", "messages_sent": 1,
      "day_number": 7, "next_followup_date": "2026-10-04", "status": "nurturing"},
     {"name": "B", "company": "c", "product_interest": "p", "market": "EU", "messages_sent": 3,
      "day_number": 21, "next_followup_date": "2026-10-07", "status": "opted_out"}]
LOG = [{"Date": "2026-09-30 04:50", "Name": "A", "Day Number": "3", "Message Sent": "hi",
        "Reply Received": "No", "Action Taken": "SENT (demo) -> +92"},
       {"Date": "2026-09-30 04:52", "Name": "A", "Day Number": "3", "Reply Received": "Yes",
        "Reply Text": "need 500 pcs", "Reply Classification": "HOT", "Action Taken": "status -> HOT"}]


def test_dashboard_counters_and_tables():
    today = date(2026, 9, 30)
    c = counters(Q, LOG, [{"x": 1}], today)
    assert c == {"in_nurture": 1, "sent_today": 1, "hot_total": 1, "opted_out": 1, "replies": 1}
    rows = queue_table(Q, today)
    assert rows[0]["Name"] == "A" and rows[0]["When"] == "in 4 days"
    assert "opted out" in rows[1]["Status"]
    lt = log_table(LOG)
    assert lt[0]["Type"] == "⬅️ reply" and "HOT" in lt[0]["Result"]
