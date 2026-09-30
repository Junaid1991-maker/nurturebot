"""NODE 3 — Message Generator.

How it works:
  1. Build facts for the lead (industry note, market note, capability, timing).
  2. Fill the day's template with those facts → a correct, safe "reference draft".
  3. Ask Groq to rewrite the draft so it sounds personal and natural.
  4. Check the AI output. If Groq fails or the output breaks a rule, send the draft instead.
So a message is ALWAYS produced, and the AI can never invent facts that aren't in step 1.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypedDict

import config
from config import SEQUENCE_DAYS, next_sequence_day

# ── Knowledge the AI is allowed to use ─────────────────────────
INDUSTRY_NOTES = {
    "towels": "hotel and laundry buyers usually compare towels on GSM, absorbency and how well "
              "they hold up to industrial washing, and they value the same weight on every repeat order",
    "bed_linen": "hotel buyers mostly judge bed linen on thread count, shrinkage and colour "
                 "consistency after repeated industrial washing",
    "knitwear": "knitwear buyers are paying more attention to fibre composition and factory "
                "traceability, not only price",
    "garments": "most garment buyers shortlist suppliers on MOQ, lead time and certifications "
                "before they even compare prices",
    "default": "buyers are increasingly choosing suppliers on reliability and clear communication, "
               "not only on price",
}
MARKET_NOTES = {
    "Gulf": "many Gulf buyers plan hotel and retail stock well ahead of Ramadan, and FOB Karachi "
            "keeps transit times to Gulf ports short",
    "EU": "EU Digital Product Passport rules for textiles are on the way (expected from around 2027), "
          "so EU buyers are starting to ask suppliers for traceability data",
    "US": "US buyers are putting more weight on dependable lead times and complete compliance paperwork",
    "Other": "many buyers are reviewing their supplier lists for the next season",
}
MARKET_TIMING = {
    "Gulf": "a lot of Gulf buyers are planning their stock ahead of Ramadan and the hotel season",
    "EU": "EU buyers are starting to prepare supplier data ahead of the Digital Product Passport rules",
    "US": "many US buyers are finalising next-quarter orders",
    "Other": "many buyers are finalising their next-quarter orders",
}
MARKET_LABEL = {"Gulf": "Gulf", "EU": "European", "US": "US", "Other": ""}

DAY_GOALS = {
    3: "VALUE: share one genuinely useful insight about their product or market. No ask, just leave the door open.",
    7: "RELEVANCE: mention the capability that matches what they are looking for. Invite a question.",
    14: "SOFT OFFER: mention the timing point and suggest a quick 15-minute call only if useful. Zero pressure.",
    21: "RE-QUALIFY: simply ask whether they are still exploring suppliers for this product. Make it easy to say 'not now'.",
    30: "CLOSE KINDLY: say you won't keep following up and the door stays open. No ask.",
}

MAX_WORDS = 120
LEFTOVER_PLACEHOLDER = re.compile(r"\[[^\]]{2,}\]|\{[a-z_]+\}")


def _mid_sentence(text: str) -> str:
    """'Terry towels 500gsm' → 'terry towels 500gsm' (keeps acronyms like 'TC' or 'GSM')."""
    text = text.strip()
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        return text[0].lower() + text[1:]
    return text


def detect_category(industry: str, product: str) -> str:
    text = f"{industry} {product}".lower()
    if any(w in text for w in ("towel", "terry")):
        return "towels"
    if any(w in text for w in ("linen", "bedsheet", "bed sheet", "sheet", "200tc", "tc ")):
        return "bed_linen"
    if "knit" in text:
        return "knitwear"
    if any(w in text for w in ("garment", "apparel", "fashion", "denim", "shirt")):
        return "garments"
    return "default"


def detect_language(phone: str) -> str:
    """Roman Urdu/English mix only makes sense for Pakistani contacts.
    A Saudi or German buyer gets clear, simple English."""
    return "roman_urdu_mix" if str(phone).startswith("+92") else "english"


@lru_cache
def load_profile() -> dict:
    return json.loads(Path(config.SENDER_PROFILE_PATH).read_text(encoding="utf-8"))


@lru_cache
def load_template(day: int) -> str:
    return (Path(config.SEQUENCES_DIR) / f"day{day}.txt").read_text(encoding="utf-8").strip()


def build_facts(lead: dict, profile: dict) -> dict:
    category = detect_category(lead.get("industry", ""), lead.get("product_interest", ""))
    market = lead.get("market") or "Other"
    if market not in MARKET_NOTES:
        market = "Other"
    # Day 3 insight: EU leads get the DPP point (most relevant); others get the product point.
    insight = MARKET_NOTES["EU"] if market == "EU" else INDUSTRY_NOTES[category]
    caps = profile.get("capabilities", {})
    return {
        "first_name": (lead.get("name") or "there").split()[0],
        "full_name": lead.get("name", ""),
        "company": lead.get("company", ""),
        "product": _mid_sentence(lead.get("product_interest") or "your products"),
        "category": category,
        "market": market,
        "market_label": MARKET_LABEL[market] or "",
        "insight": insight,
        "market_note": MARKET_NOTES[market],
        "capability": caps.get(category) or caps.get("default", ""),
        "timing": MARKET_TIMING[market],
        "language": detect_language(lead.get("phone", "")),
        "notes": "" if lead.get("notes", "").strip().upper() == "DEMO" else lead.get("notes", ""),
    }


def fill_template(day: int, facts: dict) -> str:
    text = load_template(day).format(**facts)
    return re.sub(r"your\s+buyers", "your buyers", text)  # tidy when market_label is empty


def build_prompts(day: int, facts: dict, draft: str, profile: dict) -> tuple[str, str]:
    lang_rule = (
        "Write in natural Roman Urdu mixed with English, the way Karachi business people text on WhatsApp."
        if facts["language"] == "roman_urdu_mix"
        else "Write in clear, simple English. The buyer may not be a native English speaker."
    )
    system = f"""You write short WhatsApp follow-up messages for {profile['sender_name']} at \
{profile['company']}, a {profile.get('company_type', 'textile exporter')}. The recipient is a \
buyer who showed interest earlier but was not ready to order.

RULES
- Keep the same intent as the reference draft, but make it sound personal and natural.
- 35 to 90 words. Warm, helpful, never pushy. No discounts, no fake urgency, no pressure.
- Use ONLY the facts given. Never invent numbers, prices, client names, results, certifications or dates.
- {lang_rule}
- At most one emoji. No links, no hashtags, no headings, no bullet points.
- Never mention a "sequence", "day number", "automation" or that this is a follow-up campaign.
- Output ONLY the message text. No quotes, no explanations."""

    user = f"""MESSAGE GOAL: {DAY_GOALS[day]}

LEAD
- Name: {facts['full_name']} (address them as {facts['first_name']})
- Company: {facts['company']}
- Interested in: {facts['product']}
- Market: {facts['market']}
{f"- Earlier context: {facts['notes']}" if facts['notes'] else ""}

FACTS YOU MAY USE
- Product insight: {INDUSTRY_NOTES[facts['category']]}
- Market insight: {facts['market_note']}
- Our capability for this product: {facts['capability']}

REFERENCE DRAFT (rewrite this):
{draft}"""
    return system, user


def clean_output(text: str) -> str:
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(r"^(here('s| is) (the|your) message:?)\s*", "", text, flags=re.I)
    text = text.replace("**", "*")                     # WhatsApp bold is *single*
    for odd, plain in {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u00a0": " ",
                       "\u202f": " ", "\u2009": " "}.items():
        text = text.replace(odd, plain)                # non-breaking hyphens/spaces
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def check_output(text: str) -> Optional[str]:
    """Returns a reason string if the AI output must be rejected, else None."""
    if not text:
        return "empty output"
    if LEFTOVER_PLACEHOLDER.search(text):
        return "placeholder left in output"
    if len(text.split()) > MAX_WORDS:
        return f"too long ({len(text.split())} words)"
    if re.search(r"https?://|www\.", text):
        return "contains a link"
    return None


def generate_message(lead: dict, day: int, llm=None) -> dict:
    if day not in SEQUENCE_DAYS:
        raise ValueError(f"day_number must be one of {SEQUENCE_DAYS}, got {day}")
    profile = load_profile()
    facts = build_facts(lead, profile)
    draft = fill_template(day, facts)

    message, source, reason = draft, "template", "no GROQ_API_KEY set"
    if llm is not None:
        try:
            candidate = clean_output(llm(*build_prompts(day, facts, draft, profile)))
            reason = check_output(candidate)
            if reason is None:
                message, source = candidate, "llm"
        except Exception as e:  # network, rate limit, bad key… never block the run
            reason = f"groq error: {type(e).__name__}: {e}"[:200]

    nxt = next_sequence_day(day)
    return {
        "lead_id": lead.get("lead_id", ""),
        "personalized_message": message,
        "day_number": day,
        "next_followup_day": nxt,
        "is_final_message": nxt is None,
        "language": facts["language"],
        "source": source,
        "fallback_reason": None if source == "llm" else reason,
    }


class GenState(TypedDict, total=False):
    due_leads: list[dict]
    messages: list[dict]


def generator_node(state: GenState, llm) -> GenState:
    out = []
    for lead in state.get("due_leads", []):
        try:
            out.append(generate_message(lead, int(lead["day_number"]), llm))
        except Exception as e:
            out.append({"lead_id": lead.get("lead_id", ""), "error": str(e)})
    return {"messages": out}
