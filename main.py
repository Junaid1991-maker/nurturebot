"""NurtureBot FastAPI — port 8007.

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8007
Docs: http://localhost:8007/docs
"""
from functools import lru_cache
from typing import Optional

import hashlib
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import config
from graph import build_daily_graph, build_intake_graph, run_daily
from integrations.alerts import make_email_sender
from integrations.whatsapp import make_wa_template_sender, make_wa_text_sender
from nodes.classifier import classify_reply
from nodes.reply import handle_incoming, match_lead
from nodes.generator import generate_message
from nodes.intake import WarmLead
from nodes.llm import make_groq_llm
from sheets import SheetsClient

app = FastAPI(title="NurtureBot", version="1.0.0")


def require_key(x_api_key: Optional[str] = Header(default=None), key: Optional[str] = None):
    """On Render, API_KEY is set → callers must send header X-API-Key (or ?key=).
    Locally API_KEY is empty → no key needed, so nothing changes for testing."""
    if config.API_KEY and not hmac.compare_digest((x_api_key or key or ""), config.API_KEY):
        raise HTTPException(401, "missing or wrong API key")


def meta_signature_ok(raw: bytes, header: Optional[str]) -> bool:
    """Meta signs every webhook with your App Secret. If WA_APP_SECRET is set, anything
    without a valid signature (i.e. not from Meta) is rejected."""
    if not config.WA_APP_SECRET:
        return True
    expected = "sha256=" + hmac.new(config.WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(expected, header)


@lru_cache
def get_sheets() -> SheetsClient:
    return SheetsClient()


@lru_cache
def get_llm():
    return make_groq_llm()


@lru_cache
def get_json_llm():
    return make_groq_llm(json_mode=True)


def get_email_sender():
    return make_email_sender()


def get_senders() -> dict:
    return {"text": make_wa_text_sender(), "template": make_wa_template_sender()}


def _public(lead: dict) -> dict:
    return {k: v for k, v in lead.items() if k != "_row"} | {"row": lead.get("_row")}


@app.post("/setup-sheets", dependencies=[Depends(require_key)])
def setup_sheets(sheets=Depends(get_sheets)):
    try:
        return {"actions": sheets.ensure_structure()}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/add-lead", dependencies=[Depends(require_key)])
def add_lead(lead: WarmLead, sheets=Depends(get_sheets)):
    result = build_intake_graph(sheets).invoke({"raw_lead": lead.model_dump()})
    if not result.get("added"):
        code = 409 if result.get("error_type") == "duplicate" else 400
        raise HTTPException(code, result.get("error", "unknown error"))
    rec = result["record"]
    return {"lead_id": rec["lead_id"], "added": True,
            "day_number": rec["day_number"], "first_followup": rec["next_followup_date"]}


@app.get("/due-today", dependencies=[Depends(require_key)])
def due_today(run_date: Optional[str] = None, sheets=Depends(get_sheets)):
    """Node 2 only. Optional ?run_date=2026-10-02 to simulate a future day."""
    run_date = run_date or config.today().isoformat()
    result = build_daily_graph(sheets, generate=False).invoke({"run_date": run_date})
    return {"run_date": run_date, "count": len(result["due_leads"]),
            "due_leads": [_public(l) for l in result["due_leads"]],
            "warnings": result["warnings"]}


class NurtureRequest(BaseModel):
    lead: dict
    day_number: Optional[int] = None


@app.post("/nurture", dependencies=[Depends(require_key)])
def nurture(req: NurtureRequest, llm=Depends(get_llm)):
    """Node 3 only: generate ONE message."""
    day = req.day_number or req.lead.get("day_number")
    try:
        return generate_message(req.lead, int(day), llm)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"bad day_number: {e}")


@app.get("/preview-today", dependencies=[Depends(require_key)])
def preview_today(run_date: Optional[str] = None, sheets=Depends(get_sheets), llm=Depends(get_llm)):
    """Node 2 + 3: who is due and what they WOULD receive. Sends nothing."""
    run_date = run_date or config.today().isoformat()
    result = build_daily_graph(sheets, llm).invoke({"run_date": run_date})
    by_id = {m.get("lead_id"): m for m in result.get("messages", [])}
    return {"run_date": run_date, "groq_connected": llm is not None,
            "count": len(result["due_leads"]),
            "previews": [{"name": l["name"], "company": l["company"], "market": l["market"],
                          "product": l["product_interest"]} | by_id.get(l["lead_id"], {})
                         for l in result["due_leads"]],
            "warnings": result["warnings"]}


@app.post("/run-daily", dependencies=[Depends(require_key)])
def run_daily_endpoint(dry_run: bool = False, sheets=Depends(get_sheets),
                       llm=Depends(get_llm), senders=Depends(get_senders)):
    """The full daily job (n8n calls this at 9 AM): Nodes 2 → 3 → 4 → 5.
    ?dry_run=true shows what would be sent and changes nothing."""
    return run_daily(sheets, llm, senders, dry_run=dry_run)


# ── Session 4: replies ─────────────────────────────────────────
@app.post("/incoming", dependencies=[Depends(require_key)])
async def incoming(request: Request, sheets=Depends(get_sheets), llm=Depends(get_json_llm),
                   senders=Depends(get_senders), email_sender=Depends(get_email_sender)):
    """Raw WhatsApp webhook JSON (n8n forwards it here). Returns handled=false when the
    message is not from a NurtureBot lead, so n8n can pass it to the next agent."""
    return handle_incoming(await request.json(), sheets, llm, senders, email_sender)


@app.get("/webhook")
def webhook_verify(request: Request):
    """Only used if Meta points DIRECTLY at NurtureBot (no n8n in front)."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and config.WA_VERIFY_TOKEN \
            and q.get("hub.verify_token") == config.WA_VERIFY_TOKEN:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verify token mismatch")


@app.post("/webhook")
async def webhook_receive(request: Request, sheets=Depends(get_sheets), llm=Depends(get_json_llm),
                          senders=Depends(get_senders), email_sender=Depends(get_email_sender),
                          x_hub_signature_256: Optional[str] = Header(default=None)):
    raw = await request.body()
    if not meta_signature_ok(raw, x_hub_signature_256):
        raise HTTPException(401, "invalid Meta signature")
    try:
        import json
        return handle_incoming(json.loads(raw or b"{}"), sheets, llm, senders, email_sender)
    except Exception as e:  # noqa: BLE001 — always 200, or Meta keeps retrying
        return {"handled": False, "error": f"{type(e).__name__}: {e}"}


class CheckLead(BaseModel):
    phone: str = ""
    context_id: Optional[str] = None


@app.post("/check-lead", dependencies=[Depends(require_key)])
def check_lead(body: CheckLead, sheets=Depends(get_sheets)):
    msg = {"from": "+" + body.phone.lstrip("+"), "context_id": body.context_id}
    lead, how = match_lead(msg, sheets.get_queue(), sheets.log_rows(), config.DEMO_MODE)
    return {"is_nurture_lead": lead is not None, "matched_by": how if lead else None,
            "lead_id": lead["lead_id"] if lead else None,
            "lead_name": lead["name"] if lead else None,
            "status": lead["status"] if lead else None,
            "detail": None if lead else how}


class ClassifyBody(BaseModel):
    reply_text: str
    lead_id: Optional[str] = None
    day_number: Optional[int] = None


@app.post("/classify-reply", dependencies=[Depends(require_key)])
def classify_endpoint(body: ClassifyBody, llm=Depends(get_json_llm)):
    """Node 6 only — classify text without touching the Sheet (for testing)."""
    v = classify_reply(body.reply_text, {"lead_id": body.lead_id, "day_number": body.day_number}, llm)
    action = {"HOT": "alert Junaid + status HOT", "STOP": "opt out, never message again",
              "WARM": "continue sequence"}[v["classification"]]
    return v | {"action": action}


@app.get("/ping")
def ping():
    """Cheap check for Render (doesn't touch Google Sheets)."""
    return {"ok": True}


@app.get("/health")
def health():
    base = {"service": "nurturebot", "port": 8007, "demo_mode": config.DEMO_MODE,
            "groq_configured": bool(config.GROQ_API_KEY),
            "whatsapp_configured": bool(config.WA_ACCESS_TOKEN and config.WA_PHONE_NUMBER_ID)}
    try:
        sheets = get_sheets()
        queue = sheets.get_queue()
        return base | {
            "status": "running",
            "leads_in_queue": sum(1 for l in queue if l["status"] == config.STATUS_NURTURING),
            "messages_sent_today": sheets.count_messages_on(config.today()),
            "hot_upgrades_total": sheets.count_hot_upgrades(),
        }
    except Exception as e:
        return base | {"status": "degraded", "error": f"{type(e).__name__}: {e}"}
