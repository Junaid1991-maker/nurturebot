"""LangGraph wiring.

  intake flow : add-lead → Node 1 (intake)
  daily flow  : Node 2 scheduler → Node 3 generator → prepare
                   → loop [ Node 4 sender → Node 5 updater ] until no leads left

The loop sends ONE lead, updates the Sheet for that lead, then goes back for the next.
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from nodes.generator import generator_node
from nodes.intake import IntakeState, intake_node
from nodes.scheduler import scheduler_node
from nodes.sender import SendSettings, sender_node
from nodes.updater import updater_node


class DailyState(TypedDict, total=False):
    run_date: str
    dry_run: bool
    due_leads: list[dict]
    warnings: list[str]
    messages: list[dict]
    pending: list[dict]
    current: Optional[dict]
    results: list[dict]
    sent_count: int
    note: Optional[str]


def build_intake_graph(sheets):
    g = StateGraph(IntakeState)
    g.add_node("intake", lambda s: intake_node(s, sheets))
    g.add_edge(START, "intake")
    g.add_edge("intake", END)
    return g.compile()


def prepare_node(state: DailyState, settings: SendSettings) -> DailyState:
    msgs = {m["lead_id"]: m for m in state.get("messages", []) if "error" not in m}
    pending = [{"lead": l, "message": msgs[l["lead_id"]]}
               for l in state.get("due_leads", []) if l["lead_id"] in msgs]
    note = None
    hour = config.now().hour
    if settings.demo_mode and not settings.demo_wa:
        pending, note = [], "DEMO_MODE is on but DEMO_WA_NUMBER is empty in .env"
    elif not settings.demo_mode and not (config.BUSINESS_HOURS[0] <= hour < config.BUSINESS_HOURS[1]):
        pending, note = [], "outside business hours (9:00-19:00 Karachi) - nothing sent"
    elif len(pending) > settings.max_per_run:
        note = f"{len(pending) - settings.max_per_run} more lead(s) due - they go in the next run"
        pending = pending[:settings.max_per_run]
    return {"pending": pending, "note": note, "results": [], "sent_count": 0}


def _more(state: DailyState) -> str:
    return "send" if state.get("pending") else "end"


def build_daily_graph(sheets, llm=None, generate: bool = True, send: bool = False,
                      senders: Optional[dict] = None, settings: Optional[SendSettings] = None):
    g = StateGraph(DailyState)
    g.add_node("scheduler", lambda s: scheduler_node(s, sheets))
    g.add_edge(START, "scheduler")
    if not generate:
        g.add_edge("scheduler", END)
        return g.compile()

    g.add_node("generator", lambda s: generator_node(s, llm))
    g.add_edge("scheduler", "generator")
    if not send:
        g.add_edge("generator", END)
        return g.compile()

    settings = settings or SendSettings.from_env()
    senders = senders or {}
    g.add_node("prepare", lambda s: prepare_node(s, settings))
    g.add_node("sender", lambda s: sender_node(s, sheets, senders, settings))
    g.add_node("updater", lambda s: updater_node(s, sheets))
    g.add_edge("generator", "prepare")
    g.add_conditional_edges("prepare", _more, {"send": "sender", "end": END})
    g.add_edge("sender", "updater")
    g.add_conditional_edges("updater", _more, {"send": "sender", "end": END})
    return g.compile()


def run_daily(sheets, llm, senders, settings=None, run_date=None, dry_run=False) -> dict:
    settings = settings or SendSettings.from_env()
    run_date = run_date or config.today().isoformat()
    graph = build_daily_graph(sheets, llm, send=True, senders=senders, settings=settings)
    out = graph.invoke({"run_date": run_date, "dry_run": dry_run},
                       config={"recursion_limit": 10 + 3 * settings.max_per_run})
    results = out.get("results", [])
    count = lambda prefix: sum(1 for r in results if r["status"].startswith(prefix))
    return {"run_date": run_date, "demo_mode": settings.demo_mode, "dry_run": dry_run,
            "due": len(out.get("due_leads", [])), "sent": count("SENT"),
            "failed": count("FAILED"), "skipped": count("SKIPPED"),
            "would_send": count("WOULD SEND"), "note": out.get("note"),
            "warnings": out.get("warnings", []), "results": results}
