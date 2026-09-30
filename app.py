"""NurtureBot dashboard.   Run:  streamlit run streamlit_app/app.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

import config  # noqa: E402
from sheets import SheetsClient  # noqa: E402
from streamlit_app.data import counters, log_table, queue_table  # noqa: E402

st.set_page_config(page_title="NurtureBot", page_icon="🌱", layout="wide")

# ── Password gate (only when DASHBOARD_PASSWORD is set, i.e. on Render) ──
if config.DASHBOARD_PASSWORD and not st.session_state.get("ok"):
    st.title("🌱 NurtureBot")
    pw = st.text_input("Password", type="password")
    if pw:
        if pw == config.DASHBOARD_PASSWORD:
            st.session_state.ok = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()


@st.cache_resource
def sheets():
    return SheetsClient()


@st.cache_data(ttl=60, show_spinner="Reading Google Sheets…")
def load():
    s = sheets()
    queue = [{k: v for k, v in l.items() if k != "_row"} for l in s.get_queue()]
    return queue, s.log_records(), s.hot_records()


today = config.today()
head, btn = st.columns([5, 1])
head.title("🌱 NurtureBot")
head.caption(f"WARM lead nurturing · 5 WhatsApp messages over 30 days · "
             f"{'DEMO mode (all messages go to the demo number)' if config.DEMO_MODE else 'LIVE'}"
             f" · {today:%d %b %Y}")
if btn.button("🔄 Refresh"):
    load.clear()
    st.rerun()

try:
    queue, log, hot = load()
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read Google Sheets: {e}")
    st.stop()

c = counters(queue, log, hot, today)
m = st.columns(5)
m[0].metric("In nurture", c["in_nurture"])
m[1].metric("Messages sent today", c["sent_today"])
m[2].metric("Replies received", c["replies"])
m[3].metric("🔥 HOT upgrades", c["hot_total"])
m[4].metric("Opted out", c["opted_out"])

t1, t2, t3 = st.tabs(["Active Queue", "🔥 HOT Upgrades", "Message Log"])
with t1:
    rows = queue_table(queue, today)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No leads yet. Add WARM leads with POST /add-lead.")
with t2:
    if hot:
        st.dataframe([{"When": h.get("Date"), "Name": h.get("Name"), "Company": h.get("Company"),
                       "Phone": h.get("Phone"), "Replied to": f"Day {h.get('Day Upgraded')}",
                       "Their reply": h.get("Reply Text"),
                       "Handed to Order Agent": h.get("Handed to Order Agent (Y/N)"),
                       "Outcome": h.get("Deal Outcome")} for h in reversed(hot)],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No HOT upgrades yet.")
with t3:
    rows = log_table(log)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No messages yet.")

st.caption("Data refreshes every 60 seconds · Source: Google Sheets")
