"""NODE 1 — Lead Intake: validate a WARM lead, dedupe, add to Nurture Queue."""
import re
import uuid
from datetime import date, timedelta
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field, ValidationError, field_validator

from config import (SEQUENCE_DAYS, STATUS_HOT, STATUS_NURTURING,
                    STATUS_OPTED_OUT, today)

MARKET_ALIASES = {
    "gulf": "Gulf", "uae": "Gulf", "dubai": "Gulf", "ksa": "Gulf", "saudi": "Gulf",
    "saudi arabia": "Gulf", "qatar": "Gulf", "oman": "Gulf", "kuwait": "Gulf",
    "bahrain": "Gulf", "gcc": "Gulf",
    "eu": "EU", "europe": "EU", "germany": "EU", "france": "EU", "italy": "EU",
    "spain": "EU", "netherlands": "EU",
    "us": "US", "usa": "US", "united states": "US",
}

# Phones in these statuses block a re-add. opted_out is permanent — never message them again.
BLOCKING_STATUSES = {STATUS_NURTURING, STATUS_HOT, STATUS_OPTED_OUT}


def normalize_phone(raw: str) -> str:
    s = re.sub(r"[^\d+]", "", str(raw).strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    elif s.startswith("03") and len(s) == 11:      # Pakistani local 03xxxxxxxxx
        s = "+92" + s[1:]
    elif not s.startswith("+"):
        s = "+" + s
    digits = s[1:]
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError(f"invalid phone number: {raw!r}")
    return s


class WarmLead(BaseModel):
    name: str = Field(min_length=1)
    company: str = ""
    phone: str
    industry: str = ""
    product_interest: str = ""
    market: Literal["Gulf", "EU", "US", "Other"] = "Other"
    original_score: int = Field(ge=0, le=100)
    notes: str = ""
    # Demo/backfill only: enter the lead mid-sequence so a message is due today.
    start_at_day: Optional[int] = None

    @field_validator("name", "company", "industry", "product_interest", "notes")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("market", mode="before")
    @classmethod
    def _market(cls, v):
        s = "" if v is None else str(v).strip()
        if s in {"Gulf", "EU", "US", "Other"}:
            return s
        return MARKET_ALIASES.get(s.lower(), "Other")

    @field_validator("start_at_day")
    @classmethod
    def _start_day(cls, v):
        if v is not None and v not in SEQUENCE_DAYS:
            raise ValueError(f"start_at_day must be one of {SEQUENCE_DAYS}")
        return v


class DuplicateLeadError(Exception):
    pass


def new_lead_id(on: date) -> str:
    return f"NB-{on:%y%m%d}-{uuid.uuid4().hex[:4].upper()}"


def build_record(lead: WarmLead, existing_queue: list[dict], on: date) -> dict:
    for row in existing_queue:
        if row["phone"] == lead.phone and row["status"] in BLOCKING_STATUSES:
            raise DuplicateLeadError(
                f"{lead.phone} already in queue as {row['lead_id']} (status: {row['status']})")

    if lead.start_at_day is None:                  # normal path: start today
        start, day_number, sent = on, SEQUENCE_DAYS[0], 0
    else:                                          # demo path: backdate the start
        start = on - timedelta(days=lead.start_at_day)
        day_number = lead.start_at_day
        sent = SEQUENCE_DAYS.index(lead.start_at_day)

    return {
        "lead_id": new_lead_id(on),
        "name": lead.name,
        "company": lead.company,
        "phone": lead.phone,
        "industry": lead.industry,
        "product_interest": lead.product_interest,
        "market": lead.market,
        "original_score": lead.original_score,
        "nurture_start_date": start.isoformat(),
        "last_contacted": "",
        "messages_sent": sent,
        "day_number": day_number,
        "next_followup_date": (start + timedelta(days=day_number)).isoformat(),
        "status": STATUS_NURTURING,
        "notes": lead.notes,
    }


class IntakeState(TypedDict, total=False):
    raw_lead: dict
    record: dict
    added: bool
    error: str
    error_type: str      # "validation" | "duplicate"


def intake_node(state: IntakeState, sheets) -> IntakeState:
    try:
        lead = WarmLead(**state["raw_lead"])
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        return {"added": False, "error": msgs, "error_type": "validation"}

    try:
        record = build_record(lead, sheets.get_queue(), today())
    except DuplicateLeadError as e:
        return {"added": False, "error": str(e), "error_type": "duplicate"}

    sheets.append_queue_row(record)
    return {"record": record, "added": True}
