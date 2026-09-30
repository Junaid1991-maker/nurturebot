"""NODE 2 — Schedule Checker: which nurturing leads need a message today?"""
from datetime import date
from typing import TypedDict

from config import MAX_MESSAGES, STATUS_NURTURING


def find_due_leads(queue: list[dict], on: date) -> tuple[list[dict], list[str]]:
    """Returns (due_leads, warnings).

    Uses next_followup_date <= today (not ==) so a missed day — laptop off,
    Render asleep, n8n down — is caught on the next run instead of skipped forever.
    """
    due, warnings = [], []
    for lead in queue:
        if lead["status"] != STATUS_NURTURING:
            continue
        if lead["messages_sent"] >= MAX_MESSAGES:
            warnings.append(f"{lead['lead_id']}: all {MAX_MESSAGES} sent but still 'nurturing'")
            continue
        try:
            followup = date.fromisoformat(lead["next_followup_date"])
        except ValueError:
            warnings.append(f"{lead['lead_id']} (row {lead['_row']}): bad date "
                            f"{lead['next_followup_date']!r}")
            continue
        if followup <= on:
            due.append({**lead, "overdue_days": (on - followup).days})

    due.sort(key=lambda l: (l["next_followup_date"], l["lead_id"]))
    return due, warnings


class DailyState(TypedDict, total=False):
    run_date: str
    due_leads: list[dict]
    warnings: list[str]


def scheduler_node(state: DailyState, sheets) -> DailyState:
    on = date.fromisoformat(state["run_date"])
    due, warnings = find_due_leads(sheets.get_queue(), on)
    return {"due_leads": due, "warnings": warnings}
