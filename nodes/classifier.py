"""NODE 6 — Reply Classifier: HOT / WARM / STOP.

Two layers:
  1. Rules (instant, free, always available). STOP from rules ALWAYS wins:
     an opt-out must never depend on an AI call succeeding.
  2. Groq reads the reply in context (catches "we don't need 500 pcs right now",
     Roman Urdu, sarcasm…). If Groq fails, the rules decide.
"""
import json
import re

STOP_PATTERNS = [
    r"\bstop\b", r"\bunsubscribe\b", r"\bremove me\b", r"\bnot interested\b",
    r"\bno more (messages|msgs)\b", r"\b(don'?t|do not) (message|text|contact|send)\b",
    r"\bmat bhej", r"\bband kar", r"\bnahi chahiye\b",
]
HOT_PATTERNS = {
    "quantity": r"\b\d[\d,]*\s*(pcs|pieces?|sets?|units?|dozens?|kgs?|tons?|containers?|"
                r"ctns?|cartons?|meters?|yards?|bales?)\b",
    "large number": r"\b\d{3,}[\d,]*\b",
    "timeline": r"\b(next|this|coming) (week|month)\b|\basap\b|\burgent(ly)?\b|\bjaldi\b|"
                r"\bbefore (ramadan|eid|christmas)\b|\bby (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
    "meeting": r"\b(call me|call|meeting|meet|zoom|visit|discuss)\b",
    "catalogue/sample/quote": r"\bcatalog(ue)?s?\b|\bsamples?\b|\bquot(e|ation)s?\b|\bprice ?list\b",
    "interest": r"\binterested\b|\bsounds good\b|\blet'?s talk\b|\bhaan ji\b",
}


def rule_classify(text: str) -> dict:
    t = (text or "").lower()
    stop = [p for p in STOP_PATTERNS if re.search(p, t)]
    if stop:
        return {"classification": "STOP", "confidence": 1.0, "signals": ["opt-out words"],
                "reasoning": "reply contains opt-out words"}
    hot = [name for name, p in HOT_PATTERNS.items() if re.search(p, t)]
    if hot:
        return {"classification": "HOT", "confidence": 0.7, "signals": hot,
                "reasoning": "buying signals: " + ", ".join(hot)}
    return {"classification": "WARM", "confidence": 0.5, "signals": [],
            "reasoning": "no buying or opt-out signals"}


SYSTEM = """You classify a buyer's WhatsApp reply to a textile exporter's follow-up message.

HOT  = ready to move: mentions a quantity, a timeline, asks for a call/meeting, asks for a
       catalogue, samples or a quotation, or clearly says yes/interested.
WARM = engaged but not ready: general positive reply, "tell me more", asks about prices in
       general, "maybe later", a question without commitment.
STOP = does not want messages: stop, unsubscribe, not interested, remove me, rude refusal.

Replies may be English, Arabic-English or Roman Urdu. Read the meaning, not just keywords:
"we don't need 500 pieces now" is WARM, not HOT.

Return ONLY JSON: {"classification": "HOT|WARM|STOP", "confidence": 0.0-1.0,
"reasoning": "one short sentence", "signals": ["short", "tags"]}"""


def _parse_llm(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    data = json.loads(m.group(0) if m else raw)
    label = str(data.get("classification", "")).upper().strip()
    if label not in {"HOT", "WARM", "STOP"}:
        raise ValueError(f"bad label {label!r}")
    conf = float(data.get("confidence", 0.6))
    return {"classification": label, "confidence": max(0.0, min(conf, 1.0)),
            "reasoning": str(data.get("reasoning", ""))[:200],
            "signals": [str(s) for s in data.get("signals", [])][:6]}


def classify_reply(text: str, lead: dict | None = None, llm=None) -> dict:
    rules = rule_classify(text)
    if rules["classification"] == "STOP":
        return rules | {"source": "rules"}
    if llm is None:
        return rules | {"source": "rules", "note": "no GROQ_API_KEY"}
    lead = lead or {}
    user = (f"Lead: {lead.get('name', '?')} from {lead.get('company', '?')}, interested in "
            f"{lead.get('product_interest', '?')} ({lead.get('market', '?')} market), "
            f"replying after follow-up day {lead.get('day_number', '?')}.\n\nReply:\n{text}")
    try:
        return _parse_llm(llm(SYSTEM, user)) | {"source": "llm"}
    except Exception as e:  # noqa: BLE001
        return rules | {"source": "rules", "note": f"groq failed: {type(e).__name__}"}
