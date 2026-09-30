"""Reply handling: WhatsApp webhook → find the lead → Node 6 classify → act.

Matching a reply to a lead:
  1. Reply-to (swipe/long-press → Reply): WhatsApp tells us which message was answered.
     We look up that message id in the Message Log. Exact, works in demo and live.
  2. LIVE mode only: the sender's phone number matches a lead's phone.
  In DEMO mode every lead "is" your phone, so only reply-to is used — otherwise a random
  "Hi" from you would be treated as a lead reply.

Anything not matched returns handled=False so n8n passes it to the next agent
(LeadHunterBot / Order Agent).
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from config import STATUS_CONVERTED, STATUS_HOT, STATUS_OPTED_OUT
from integrations.alerts import send_hot_alert
from nodes.classifier import classify_reply

WAMID_COL = 9          # "WA Message ID" is the 10th Message Log column (0-based 9)


# ── Parse Meta's webhook JSON ──────────────────────────────────
def parse_meta_payload(payload: dict) -> dict:
    messages, statuses = [], []
    for entry in (payload or {}).get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                     for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                kind = m.get("type", "")
                if kind == "text":
                    text = m.get("text", {}).get("body", "")
                elif kind == "button":
                    text = m.get("button", {}).get("text", "")
                elif kind == "interactive":
                    it = m.get("interactive", {})
                    text = (it.get("button_reply") or it.get("list_reply") or {}).get("title", "")
                else:
                    text = f"[{kind or 'unknown'} message]"
                messages.append({"from": "+" + m.get("from", "").lstrip("+"), "id": m.get("id", ""),
                                 "type": kind, "text": text,
                                 "context_id": (m.get("context") or {}).get("id"),
                                 "profile_name": names.get(m.get("from"), "")})
            for s in value.get("statuses", []):
                err = (s.get("errors") or [{}])[0]
                statuses.append({"id": s.get("id", ""), "status": s.get("status", ""),
                                 "recipient": s.get("recipient_id", ""),
                                 "error_code": err.get("code"), "error_title": err.get("title", "")})
    return {"messages": messages, "statuses": statuses}


# ── Matching ───────────────────────────────────────────────────
def replied_day(log_rows: list[list[str]], lead: dict, context_id: Optional[str]):
    """Day of the message the lead is answering. The queue's day_number has already
    moved on to the NEXT message, so it would be wrong in the alert."""
    if context_id:
        for r in log_rows:
            if len(r) > WAMID_COL and r[WAMID_COL] == context_id and r[3]:
                return int(r[3]) if str(r[3]).isdigit() else r[3]
    sent = [r for r in log_rows if len(r) > 8 and r[1] == lead["lead_id"]
            and r[8].startswith("SENT") and str(r[3]).isdigit()]
    return int(sent[-1][3]) if sent else lead["day_number"]


def lead_for_wamid(log_rows: list[list[str]], wamid: str) -> Optional[str]:
    for r in log_rows:
        if len(r) > WAMID_COL and r[WAMID_COL] == wamid:
            return r[1]
    return None


def match_lead(msg: dict, queue: list[dict], log_rows: list[list[str]], demo_mode: bool):
    by_id = {l["lead_id"]: l for l in queue}
    if msg.get("context_id"):
        lead_id = lead_for_wamid(log_rows, msg["context_id"])
        if lead_id in by_id:
            return by_id[lead_id], "reply-to"
    if not demo_mode:
        same_phone = [l for l in queue if l["phone"] == msg["from"]]
        if same_phone:          # newest row wins if a phone was re-nurtured
            return same_phone[-1], "phone"
    return None, ("demo mode: long-press the message and tap Reply" if demo_mode
                  else "phone not in Nurture Queue")


# ── LangGraph: matcher → classifier (Node 6) → actions ─────────
class ReplyState(TypedDict, total=False):
    msg: dict
    lead: Optional[dict]
    match: str
    verdict: dict
    result: dict


def build_reply_graph(sheets, llm, senders: dict, email_sender, demo_mode: bool):
    def matcher(state: ReplyState) -> ReplyState:
        msg = state["msg"]
        log_rows = sheets.log_rows()
        if any(len(r) > WAMID_COL and r[WAMID_COL] == msg["id"] for r in log_rows):
            return {"lead": None, "result": {"handled": True, "duplicate": True,
                                             "detail": "already processed (Meta retry)"}}
        lead, how = match_lead(msg, sheets.get_queue(), log_rows, demo_mode)
        if lead is None or lead["status"] == STATUS_CONVERTED:
            return {"lead": None, "result": {"handled": False,
                                             "detail": how if lead is None else "lead already converted"}}
        day = replied_day(log_rows, lead, msg.get("context_id"))
        return {"lead": lead | {"replied_day": day}, "match": how}

    def classifier(state: ReplyState) -> ReplyState:
        lead = state["lead"]
        if lead["status"] == STATUS_OPTED_OUT:
            return {"verdict": {"classification": "IGNORED", "reasoning": "lead opted out earlier",
                                "source": "rules", "confidence": 1.0}}
        return {"verdict": classify_reply(state["msg"]["text"], lead, llm)}

    def actions(state: ReplyState) -> ReplyState:
        msg, lead, verdict = state["msg"], state["lead"], state["verdict"]
        label = verdict["classification"]
        now = config.now()
        to = config.DEMO_WA_NUMBER if demo_mode else lead["phone"]
        text_sender = senders.get("text")
        done = []

        if label == "HOT":
            if lead["status"] != STATUS_HOT:
                sheets.update_queue_cells(lead["_row"], {"status": STATUS_HOT})
                sheets.append_hot_row([now.strftime("%Y-%m-%d %H:%M"), lead["lead_id"], lead["name"],
                                       lead["company"], lead["phone"], lead["replied_day"],
                                       msg["text"], "N", ""])
                done.append("status -> HOT")
            done += send_hot_alert(lead, msg["text"], verdict, email_sender, text_sender)
            if config.AUTO_ACK and text_sender and lead["status"] != STATUS_HOT:
                first = (lead["name"] or "there").split()[0]
                try:
                    text_sender(to, f"Thank you {first}! {_sender_name()} will get back to you "
                                    f"personally very shortly. 🙏")
                    done.append("thank-you sent")
                except Exception as e:  # noqa: BLE001
                    done.append(f"thank-you failed: {str(e)[:60]}")
        elif label == "STOP":
            sheets.update_queue_cells(lead["_row"], {"status": STATUS_OPTED_OUT})
            done.append("status -> opted_out (no more messages)")
            if config.AUTO_ACK and text_sender:
                try:
                    text_sender(to, "Understood, you won't receive any more messages from us. "
                                    "Take care! 🙏")
                    done.append("opt-out confirmed")
                except Exception as e:  # noqa: BLE001
                    done.append(f"opt-out confirmation failed: {str(e)[:60]}")
        elif label == "WARM":
            done.append("sequence continues")
        else:
            done.append("ignored (opted out earlier)")

        sheets.append_log_row([now.strftime("%Y-%m-%d %H:%M"), lead["lead_id"], lead["name"],
                               lead["replied_day"], "", "Yes", msg["text"], label,
                               "; ".join(done), msg["id"]])
        return {"result": {"handled": True, "lead_id": lead["lead_id"], "name": lead["name"],
                           "matched_by": state.get("match"), "classification": label,
                           "confidence": verdict.get("confidence"),
                           "reasoning": verdict.get("reasoning"), "source": verdict.get("source"),
                           "actions": done}}

    g = StateGraph(ReplyState)
    g.add_node("matcher", matcher)
    g.add_node("classifier", classifier)
    g.add_node("actions", actions)
    g.add_edge(START, "matcher")
    g.add_conditional_edges("matcher", lambda s: "go" if s.get("lead") else "stop",
                            {"go": "classifier", "stop": END})
    g.add_edge("classifier", "actions")
    g.add_edge("actions", END)
    return g.compile()


def _sender_name() -> str:
    try:
        from nodes.generator import load_profile
        return load_profile().get("sender_name", "our team")
    except Exception:  # noqa: BLE001
        return "our team"


def handle_status(st: dict, sheets) -> Optional[dict]:
    """Meta reports delivery failures AFTER accepting a message (e.g. 24h window)."""
    if st["status"] != "failed":
        return None
    lead_id = lead_for_wamid(sheets.log_rows(), st["id"]) or ""
    sheets.append_log_row([config.now().strftime("%Y-%m-%d %H:%M"), lead_id, "", "", "", "", "", "",
                           f"DELIVERY FAILED (code {st['error_code']}): {st['error_title']}",
                           st["id"] + ":status"])
    return {"lead_id": lead_id, "delivery_failed": True, "code": st["error_code"],
            "error": st["error_title"]}


def handle_incoming(payload: dict, sheets, llm, senders: dict, email_sender,
                    demo_mode: Optional[bool] = None) -> dict:
    demo = config.DEMO_MODE if demo_mode is None else demo_mode
    parsed = parse_meta_payload(payload)
    graph = build_reply_graph(sheets, llm, senders, email_sender, demo)
    results = [graph.invoke({"msg": m})["result"] | {"from": m["from"], "text": m["text"]}
               for m in parsed["messages"]]
    failures = [r for r in (handle_status(s, sheets) for s in parsed["statuses"]) if r]
    return {"handled": any(r.get("handled") for r in results) or bool(failures),
            "results": results, "delivery_failures": failures}
