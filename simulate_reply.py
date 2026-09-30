"""Pretend a demo lead replied on WhatsApp — no webhook or public URL needed.
It builds the exact JSON Meta would send and runs the full reply flow
(Sheets update, HOT alert email/WhatsApp, thank-you / opt-out message).

    python simulate_reply.py Ahmed "Yes interested, need 500 pieces"
    python simulate_reply.py Sarah "stop sending me messages"
    python simulate_reply.py Mohammed "sounds nice, what are your prices?"
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import config  # noqa: E402
from integrations.alerts import make_email_sender  # noqa: E402
from integrations.whatsapp import make_wa_template_sender, make_wa_text_sender  # noqa: E402
from nodes.llm import make_groq_llm  # noqa: E402
from nodes.reply import WAMID_COL, handle_incoming  # noqa: E402
from sheets import SheetsClient  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    who, text = sys.argv[1].lower(), " ".join(sys.argv[2:])
    sheets = SheetsClient()
    lead = next((l for l in sheets.get_queue() if who in l["name"].lower()), None)
    if not lead:
        sys.exit(f"No lead matching '{who}' in the Nurture Queue")

    # the WhatsApp id of the last message we SENT this lead = what they are replying to
    sent = [r for r in sheets.log_rows() if r[1] == lead["lead_id"] and len(r) > WAMID_COL
            and r[WAMID_COL] and r[8].startswith("SENT")]
    context_id = sent[-1][WAMID_COL] if sent else None
    if not context_id and config.DEMO_MODE:
        sys.exit(f"{lead['name']} has no sent message with a WhatsApp id yet.\n"
                 "Run  python reset_demo.py  then  python run_daily.py  first.")

    sender = config.DEMO_WA_NUMBER if config.DEMO_MODE else lead["phone"]
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": sender.lstrip("+"), "profile": {"name": lead["name"]}}],
        "messages": [{"from": sender.lstrip("+"), "id": f"wamid.SIM{int(time.time() * 1000)}",
                      "type": "text", "text": {"body": text},
                      **({"context": {"id": context_id}} if context_id else {})}]}}]}]}

    out = handle_incoming(payload, sheets, make_groq_llm(json_mode=True),
                          {"text": make_wa_text_sender(), "template": make_wa_template_sender()},
                          make_email_sender())
    for r in out["results"]:
        if not r.get("handled"):
            print("NOT HANDLED:", r.get("detail"))
            continue
        print(f"{r['name']}  →  {r['classification']}  ({r.get('source')}, "
              f"confidence {r.get('confidence')})")
        print(f"why:     {r.get('reasoning')}")
        print("actions: " + "\n         ".join(r.get("actions", [])))
