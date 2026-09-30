"""NODE 4 — WhatsApp Sender (one lead per pass through the graph loop).

Safety rules (same as LeadHunterBot services/send.py):
- DEMO_MODE=true: every message goes to DEMO_WA_NUMBER, never to the lead.
- Lead status is re-read from Sheets right before sending: if the lead replied STOP
  or went HOT a minute ago, they are skipped.
- If the lead's day number already moved on, it is skipped → no double sends.
- Live mode: only 9:00–19:00 Karachi time, max N per run, pause between messages.
"""
import re
import time
from dataclasses import dataclass

import config

SLEEP = time.sleep   # tests replace this


@dataclass
class SendSettings:
    demo_mode: bool = True
    demo_wa: str = ""
    delay_seconds: float = 30
    max_per_run: int = 20
    mode: str = "template"
    template_name: str = ""
    template_lang: str = "en"

    @classmethod
    def from_env(cls):
        return cls(demo_mode=config.DEMO_MODE, demo_wa=config.DEMO_WA_NUMBER,
                   delay_seconds=min(config.SEND_DELAY_SECONDS, 3) if config.DEMO_MODE
                   else config.SEND_DELAY_SECONDS,
                   max_per_run=config.MAX_SENDS_PER_RUN, mode=config.WA_SEND_MODE,
                   template_name=config.WA_NURTURE_TEMPLATE,
                   template_lang=config.WA_TEMPLATE_LANG)


def to_template_params(first_name: str, message: str) -> list[str]:
    """Template body is:  'Hi {{1}}, {{2}} ...'.  Meta forbids newlines in parameters and
    we don't want 'Hi Ahmed, Salam Ahmed,' twice, so drop the greeting and flatten."""
    body = message.strip()
    first_line_end = re.search(r"[,\n]", body[:60])
    if first_line_end and first_name.lower() in body[:first_line_end.start() + 1].lower():
        body = body[first_line_end.end():]
    body = re.sub(r"\s*\n+\s*", " ", body)
    body = re.sub(r" {2,}", " ", body).strip()
    return [first_name, body[:900]]


def sender_node(state: dict, sheets, senders: dict, settings: SendSettings) -> dict:
    pending = list(state.get("pending", []))
    item = pending.pop(0)
    lead, msg = item["lead"], item["message"]
    result = {"lead_id": lead["lead_id"], "name": lead["name"], "day_number": msg["day_number"],
              "message": msg["personalized_message"], "source": msg.get("source"),
              "delivered_to": None, "wa_message_id": None}

    fresh = {l["lead_id"]: l for l in sheets.get_queue()}.get(lead["lead_id"])
    delivered_to = settings.demo_wa if settings.demo_mode else (fresh or lead)["phone"]
    sent_count = state.get("sent_count", 0)

    if fresh is None:
        result |= {"status": "SKIPPED", "detail": "lead no longer in the queue"}
    elif fresh["status"] != config.STATUS_NURTURING:
        result |= {"status": "SKIPPED", "detail": f"status is now {fresh['status']}"}
    elif int(fresh["day_number"]) != int(msg["day_number"]):
        result |= {"status": "SKIPPED", "detail": "already sent (day number moved on)"}
    elif state.get("dry_run"):
        result |= {"status": "WOULD SEND", "delivered_to": delivered_to}
    else:
        try:
            if sent_count:
                SLEEP(settings.delay_seconds)
            use_text = settings.demo_mode or settings.mode == "text"
            if use_text:
                if senders.get("text") is None:
                    raise RuntimeError("WhatsApp not configured (WA_ACCESS_TOKEN / WA_PHONE_NUMBER_ID)")
                wa_id = senders["text"](delivered_to, msg["personalized_message"])
            else:
                if senders.get("template") is None:
                    raise RuntimeError("WhatsApp not configured (WA_ACCESS_TOKEN / WA_PHONE_NUMBER_ID)")
                if not settings.template_name:
                    raise RuntimeError("WA_NURTURE_TEMPLATE is empty - live mode needs an approved template")
                first = (fresh["name"] or "there").split()[0]
                wa_id = senders["template"](delivered_to, settings.template_name,
                                            settings.template_lang,
                                            to_template_params(first, msg["personalized_message"]))
            result |= {"status": "SENT (demo)" if settings.demo_mode else "SENT",
                       "delivered_to": delivered_to, "wa_message_id": wa_id}
            sent_count += 1
        except Exception as e:  # noqa: BLE001
            result |= {"status": "FAILED", "detail": str(e)[:300], "delivered_to": delivered_to}

    return {"pending": pending, "current": result | {"_lead": fresh or lead},
            "sent_count": sent_count}
