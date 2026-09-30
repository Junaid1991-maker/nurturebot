"""The full daily job from the command line (same as POST /run-daily).

    python run_daily.py --dry-run    show what would be sent, change nothing
    python run_daily.py              send for real (DEMO_MODE=true -> only to your number)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from graph import run_daily  # noqa: E402
from integrations.whatsapp import make_wa_template_sender, make_wa_text_sender  # noqa: E402
from nodes.llm import make_groq_llm  # noqa: E402
from nodes.sender import SendSettings  # noqa: E402
from sheets import SheetsClient  # noqa: E402

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    s = SendSettings.from_env()
    print(f"Mode: {'DEMO (all messages -> ' + s.demo_wa + ')' if s.demo_mode else 'LIVE'}"
          f"{'  ·  DRY RUN' if dry else ''}\n")
    out = run_daily(SheetsClient(), make_groq_llm(),
                    {"text": make_wa_text_sender(), "template": make_wa_template_sender()},
                    settings=s, dry_run=dry)
    for r in out["results"]:
        print(f"{r['lead_id']}  {r['name']:<18} Day {r['day_number']:<3} {r['status']}"
              + (f" -> {r['delivered_to']}" if r.get("delivered_to") else "")
              + (f"\n      {r['detail']}" if r.get("detail") else ""))
    if out["note"]:
        print("\nNOTE:", out["note"])
    if not out["results"] and not out["note"]:
        print("Nobody is due today. (Demo: run  python reset_demo.py  to make the 3 demo leads due again.)")
    for w in out["warnings"]:
        print("WARNING:", w)
    print(f"\nDue: {out['due']}  Sent: {out['sent']}  Failed: {out['failed']}  "
          f"Skipped: {out['skipped']}" + (f"  Would send: {out['would_send']}" if dry else ""))
