"""NurtureBot configuration: env vars, sheet structure, sequence rules."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# ── Environment ────────────────────────────────────────────────
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Karachi"))
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
DEMO_WA_NUMBER = os.getenv("DEMO_WA_NUMBER", "")

# ── Sequence ───────────────────────────────────────────────────
# Days are counted from nurture_start_date (absolute), not from the last message.
SEQUENCE_DAYS = [3, 7, 14, 21, 30]
MAX_MESSAGES = len(SEQUENCE_DAYS)

STATUS_NURTURING = "nurturing"
STATUS_HOT = "HOT"
STATUS_ARCHIVED = "archived"
STATUS_OPTED_OUT = "opted_out"
STATUS_CONVERTED = "converted"
ALL_STATUSES = {STATUS_NURTURING, STATUS_HOT, STATUS_ARCHIVED, STATUS_OPTED_OUT, STATUS_CONVERTED}

# ── Google Sheets structure ────────────────────────────────────
TAB_QUEUE = "Nurture Queue"
TAB_LOG = "Message Log"
TAB_HOT = "HOT Upgrades"

# (code_key, sheet header) — order = column order in the sheet
QUEUE_COLUMNS = [
    ("lead_id", "Lead ID"),
    ("name", "Name"),
    ("company", "Company"),
    ("phone", "Phone"),
    ("industry", "Industry"),
    ("product_interest", "Product Interest"),
    ("market", "Market"),
    ("original_score", "Original Score"),
    ("nurture_start_date", "Nurture Start Date"),
    ("last_contacted", "Last Contacted"),
    ("messages_sent", "Messages Sent"),
    ("day_number", "Day Number"),          # day of the NEXT message due (3/7/14/21/30)
    ("next_followup_date", "Next Follow-up Date"),
    ("status", "Status"),
    ("notes", "Notes"),
]
LOG_HEADERS = ["Date", "Lead ID", "Name", "Day Number", "Message Sent",
               "Reply Received", "Reply Text", "Reply Classification", "Action Taken",
               "WA Message ID"]   # Session 4: links a reply to the exact message it answers
HOT_HEADERS = ["Date", "Lead ID", "Name", "Company", "Phone", "Day Upgraded",
               "Reply Text", "Handed to Order Agent (Y/N)", "Deal Outcome"]

QUEUE_HEADERS = [h for _, h in QUEUE_COLUMNS]
TABS = [(TAB_QUEUE, QUEUE_HEADERS), (TAB_LOG, LOG_HEADERS), (TAB_HOT, HOT_HEADERS)]


def today() -> date:
    """Today's date in Karachi time (server may run in UTC on Render)."""
    return datetime.now(TZ).date()


def next_sequence_day(current_day: int) -> int | None:
    """3→7→14→21→30→None (None = sequence finished)."""
    idx = SEQUENCE_DAYS.index(current_day)
    return SEQUENCE_DAYS[idx + 1] if idx + 1 < len(SEQUENCE_DAYS) else None

# ── Session 2: message generation ──────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SEQUENCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sequences")
SENDER_PROFILE_PATH = os.getenv("SENDER_PROFILE_PATH",
                                os.path.join(SEQUENCES_DIR, "sender_profile.json"))

# ── Session 3: sending ─────────────────────────────────────────
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_API_VERSION = os.getenv("WA_API_VERSION", "v23.0")
# LIVE mode: "template" (works any time, needs a Meta-approved template) or
# "text" (free-form, only reaches people who messaged you in the last 24 hours).
# DEMO mode always uses "text" to DEMO_WA_NUMBER.
WA_SEND_MODE = os.getenv("WA_SEND_MODE", "template").strip().lower()
WA_NURTURE_TEMPLATE = os.getenv("WA_NURTURE_TEMPLATE", "")
WA_TEMPLATE_LANG = os.getenv("WA_TEMPLATE_LANG", "en")
SEND_DELAY_SECONDS = float(os.getenv("SEND_DELAY_SECONDS", "30"))
MAX_SENDS_PER_RUN = int(os.getenv("MAX_SENDS_PER_RUN", "20"))
BUSINESS_HOURS = (9, 19)          # live sends only 9:00–19:00 Karachi time
MIN_GAP_DAYS = 3                  # never two messages to one lead closer than this
RECHECK_AFTER_DAYS = 30           # archived leads: monthly re-check date


def now():
    return datetime.now(TZ)

# ── Session 4: replies + alerts ────────────────────────────────
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
ALERT_WA_NUMBER = os.getenv("ALERT_WA_NUMBER", "")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
AUTO_ACK = os.getenv("AUTO_ACK", "true").lower() == "true"   # thank HOT leads / confirm STOP

# ── Session 5: deployment + security ───────────────────────────
API_KEY = os.getenv("API_KEY", "")                    # protects /run-daily etc. on Render
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")        # verifies webhooks really come from Meta
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")  # alternative to a file
