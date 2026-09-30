import sys
sys.stdout.reconfigure(encoding="utf-8")
"""Session 2 check: print the message each due lead would get today (sends nothing).
Run: python preview_messages.py            (today)
     python preview_messages.py 2026-10-03 (simulate a date)
"""
import sys

import config
from graph import build_daily_graph
from nodes.llm import make_groq_llm
from sheets import SheetsClient

if __name__ == "__main__":
    run_date = sys.argv[1] if len(sys.argv) > 1 else config.today().isoformat()
    llm = make_groq_llm()
    print(f"Run date: {run_date}   Groq: {'connected' if llm else 'NOT SET - using templates'}\n")
    result = build_daily_graph(SheetsClient(), llm).invoke({"run_date": run_date})
    leads = {l["lead_id"]: l for l in result["due_leads"]}
    if not leads:
        print("Nobody is due on this date.")
    for m in result.get("messages", []):
        lead = leads.get(m.get("lead_id"), {})
        print("=" * 64)
        print(f"{lead.get('name')} | {lead.get('company')} | {lead.get('market')} | Day {m.get('day_number')}")
        print(f"source: {m.get('source')}   language: {m.get('language')}"
              + (f"   (fallback: {m['fallback_reason']})" if m.get("fallback_reason") else ""))
        print("-" * 64)
        print(m.get("personalized_message") or m.get("error"))
    print("=" * 64)
    for w in result.get("warnings", []):
        print("WARNING:", w)
