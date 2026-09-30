"""NODE 5 — Sheets Updater. Runs right after EACH send, so a crash halfway through
a run never causes a lead to be messaged twice."""
from datetime import date, timedelta

import config
from config import MIN_GAP_DAYS, RECHECK_AFTER_DAYS, STATUS_ARCHIVED, next_sequence_day


def compute_updates(lead: dict, sent_on: date) -> dict:
    day = int(lead["day_number"])
    nxt = next_sequence_day(day)
    updates = {"last_contacted": sent_on.isoformat(),
               "messages_sent": int(lead["messages_sent"]) + 1}
    if nxt is None:                      # Day 30 sent → archive, re-check in a month
        updates |= {"status": STATUS_ARCHIVED,
                    "next_followup_date": (sent_on + timedelta(days=RECHECK_AFTER_DAYS)).isoformat(),
                    "notes": (lead.get("notes", "") + " | archived after Day 30").strip(" |")}
    else:
        start = date.fromisoformat(lead["nurture_start_date"])
        # Normally start + next day. If this send was late, keep at least MIN_GAP_DAYS
        # so a late lead doesn't get two messages on back-to-back days.
        planned = start + timedelta(days=nxt)
        updates |= {"day_number": nxt,
                    "next_followup_date": max(planned, sent_on + timedelta(days=MIN_GAP_DAYS)).isoformat()}
    return updates


def log_row(result: dict, stamp: str) -> list:
    action = result["status"]
    if result.get("delivered_to") and result["status"].startswith("SENT"):
        action += f" -> {result['delivered_to']}"
    if result.get("detail"):
        action += f": {result['detail']}"
    return [stamp, result["lead_id"], result["name"], result["day_number"],
            result["message"], "No", "", "", action, result.get("wa_message_id") or ""]


def updater_node(state: dict, sheets) -> dict:
    cur = dict(state["current"])
    lead = cur.pop("_lead")
    pending = state.get("pending", [])
    if not state.get("dry_run"):
        now = config.now()
        try:
            if cur["status"].startswith("SENT"):
                sheets.update_queue_cells(lead["_row"], compute_updates(lead, now.date()))
            sheets.append_log_row(log_row(cur, now.strftime("%Y-%m-%d %H:%M")))
        except Exception as e:  # noqa: BLE001
            # The message went out but the Sheet didn't update. Stop the run so nothing
            # is sent twice, and say exactly what to fix.
            cur["detail"] = (f"SENT but Sheets update failed ({e}). Update row {lead['_row']} "
                             "by hand before the next run.")[:300]
            pending = []
    return {"results": state.get("results", []) + [cur], "current": None, "pending": pending}
