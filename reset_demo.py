"""Delete the 3 DEMO leads from the Nurture Queue and add them again, due today.
Use this before every demo recording. Real leads are never touched."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from graph import build_intake_graph  # noqa: E402
from seed_demo import DEMO_LEADS  # noqa: E402
from sheets import SheetsClient  # noqa: E402

if __name__ == "__main__":
    sheets = SheetsClient()
    demo_rows = [l["_row"] for l in sheets.get_queue() if l["notes"].split("|")[0].strip() == "DEMO"]
    sheets.delete_queue_rows(demo_rows)
    print(f"Removed {len(demo_rows)} old demo row(s)")
    graph = build_intake_graph(sheets)
    for lead in DEMO_LEADS:
        r = graph.invoke({"raw_lead": lead})
        print(("✓ " + r["record"]["lead_id"] + "  " + lead["name"]) if r.get("added")
              else f"✗ {lead['name']}: {r['error']}")
