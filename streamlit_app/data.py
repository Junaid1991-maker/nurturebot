"""Pure functions behind the dashboard (tested without Streamlit or Google)."""
from datetime import date

STATUS_BADGE = {"nurturing": "🟡 nurturing", "HOT": "🔥 HOT", "archived": "⚪ archived",
                "opted_out": "🛑 opted out", "converted": "✅ converted"}
CLASS_BADGE = {"HOT": "🔥 HOT", "WARM": "🟡 WARM", "STOP": "🛑 STOP", "IGNORED": "⚪ ignored"}


def counters(queue: list[dict], log: list[dict], hot: list[dict], today: date) -> dict:
    t = today.isoformat()
    return {
        "in_nurture": sum(1 for l in queue if l["status"] == "nurturing"),
        "sent_today": sum(1 for r in log if str(r.get("Date", "")).startswith(t)
                          and str(r.get("Action Taken", "")).startswith("SENT")),
        "hot_total": len(hot),
        "opted_out": sum(1 for l in queue if l["status"] == "opted_out"),
        "replies": sum(1 for r in log if r.get("Reply Received") == "Yes"),
    }


def queue_table(queue: list[dict], today: date) -> list[dict]:
    rows = []
    for l in sorted(queue, key=lambda x: (x["status"] != "nurturing", x["next_followup_date"])):
        due = l["next_followup_date"]
        when = ""
        if l["status"] == "nurturing" and due:
            try:
                d = (date.fromisoformat(due) - today).days
                when = "due today" if d <= 0 else f"in {d} day{'s' if d > 1 else ''}"
            except ValueError:
                when = "bad date"
        rows.append({"Name": l["name"], "Company": l["company"], "Product": l["product_interest"],
                     "Market": l["market"], "Sent": f"{l['messages_sent']}/5",
                     "Next message": f"Day {l['day_number']}" if l["status"] == "nurturing" else "",
                     "Next date": due, "When": when,
                     "Status": STATUS_BADGE.get(l["status"], l["status"])})
    return rows


def log_table(log: list[dict], limit: int = 200) -> list[dict]:
    out = []
    for r in reversed(log[-limit:]):
        is_reply = r.get("Reply Received") == "Yes"
        text = r.get("Reply Text") if is_reply else r.get("Message Sent")
        out.append({"When": r.get("Date"), "Lead": r.get("Name"), "Day": r.get("Day Number"),
                    "Type": "⬅️ reply" if is_reply else "➡️ sent",
                    "Text": (text or "")[:140] + ("…" if len(text or "") > 140 else ""),
                    "Result": CLASS_BADGE.get(r.get("Reply Classification"), "")
                    or str(r.get("Action Taken", ""))[:60]})
    return out
