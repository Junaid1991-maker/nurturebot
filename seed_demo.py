import sys
sys.stdout.reconfigure(encoding="utf-8")
"""Load the 3 demo WARM leads, each already due today (Day 3 / 7 / 14).

Phones are distinct fake numbers so dedup works. DEMO_MODE (Session 3)
redirects every actual WhatsApp send to DEMO_WA_NUMBER — your phone.
Run: python seed_demo.py
"""
from graph import build_intake_graph
from sheets import SheetsClient

DEMO_LEADS = [
    dict(name="Ahmed Al-Rashid", company="Dubai Laundry Services LLC",
         phone="+971500000001", industry="Hotel/laundry supplies",
         product_interest="Terry towels 500gsm", market="Gulf",
         original_score=65, start_at_day=3, notes="DEMO"),
    dict(name="Mohammed Hassan", company="Riyadh Home Textiles Trading",
         phone="+966500000002", industry="Wholesale textiles",
         product_interest="Bed linen 200TC", market="Gulf",
         original_score=58, start_at_day=7, notes="DEMO"),
    dict(name="Sarah Khan", company="Berlin Fashion Imports GmbH",
         phone="+491500000003", industry="Fashion retail",
         product_interest="Knitwear", market="EU",
         original_score=62, start_at_day=14, notes="DEMO"),
]

if __name__ == "__main__":
    graph = build_intake_graph(SheetsClient())
    for lead in DEMO_LEADS:
        r = graph.invoke({"raw_lead": lead})
        if r.get("added"):
            rec = r["record"]
            print(f"✓ {rec['lead_id']}  {rec['name']:<18} Day {rec['day_number']:<3} due {rec['next_followup_date']}")
        else:
            print(f"✗ {lead['name']}: {r['error']}")
