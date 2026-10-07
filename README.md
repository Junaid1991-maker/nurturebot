# 🌱 NurtureBot — AI WhatsApp Lead Nurturing for Textile Exporters

NurtureBot follows up with **WARM B2B leads on WhatsApp** automatically: 5 personalised messages over 30 days, AI classification of every reply, and an instant alert to the sales team when a lead turns **HOT**.

Built for Pakistani textile exporters, where warm buyer leads (hotels, wholesalers, fashion importers) are often lost simply because nobody follows up.

> **Stage 3 of the Sales Automation Engine** — LeadHunter finds leads → NurtureBot warms them → Order Agent converts them.

---

## What it does

| Step | What happens |
|---|---|
| 1. Daily run (9:00 AM PKT) | Finds every lead with a follow-up due today |
| 2. Write | Groq LLM writes a message for that buyer (product, market, timing), based on proven templates + verified facts from `sender_profile.json` |
| 3. Send | Sends via Meta WhatsApp Cloud API and logs it in Google Sheets |
| 4. Listen | Buyer replies on WhatsApp → reply is matched to the lead and classified **HOT / WARM / STOP** |
| 5. Act | **HOT** → WhatsApp alert to sales team + row in *HOT Upgrades* · **WARM** → sequence continues · **STOP** → opted out + confirmation, never messaged again |

**Sequence:** Day 3 → Day 7 → Day 14 → Day 21 → Day 30.

**Safety rules**
- STOP / opt-out keywords are checked by rules first — **rules always win over the AI**.
- AI output is validated (no placeholders, no links, length limits); if it fails, a safe template is used instead.
- Template parameters are cleaned (greeting dropped, no newlines) to meet Meta's rules.

---

## Example HOT alert

```
🔥 HOT LEAD — NurtureBot

Mohammed Hassan — Riyadh Home Textiles Trading
Wants: Bed linen 200TC · Gulf market
Replied to follow-up Day 7

Their reply:
"Yes interested, need 500 pieces"

Why HOT: Buyer explicitly says interested and specifies quantity (llm, confidence 99%)

Next step: call or message them today.
```

---

## Architecture

```
GitHub Actions (cron 04:00 UTC = 9 AM PKT)
        │  POST /run-daily
        ▼
NurtureBot API (FastAPI + LangGraph, Render) ──► Groq LLM (message writing + reply classification)
        │                                   ──► Google Sheets (Nurture Queue · Message Log · HOT Upgrades)
        ▼
Meta WhatsApp Cloud API ──► buyer's WhatsApp
        ▲
        │  buyer replies
n8n router (Webhook) → LeadHunter check → NurtureBot /incoming → handled? stop : Order Agent

Streamlit dashboard (Render, password-protected) ◄── Google Sheets
```

---

## Tech stack

Python 3.11 · LangGraph · FastAPI · Groq (`openai/gpt-oss-120b`) · Meta WhatsApp Cloud API · Google Sheets (gspread) · Streamlit · n8n · GitHub Actions · Render · pytest (63 tests)

---

## API endpoints

All endpoints except `/ping`, `/health` and `/webhook` require the header `X-API-Key`.

| Endpoint | Purpose |
|---|---|
| `GET /ping` | Liveness check |
| `GET /health` | Status, demo mode, queue counts |
| `POST /add-lead` | Add a WARM lead to the nurture queue |
| `GET /due-today` | Leads with a message due today |
| `POST /nurture` | Generate + send for a single lead |
| `GET /preview-today` | Preview today's messages without sending |
| `POST /run-daily` | Run the full daily send |
| `POST /incoming` | Raw Meta webhook JSON (used by n8n) → returns `handled: true/false` |
| `POST /check-lead` | Look up a lead |
| `POST /classify-reply` | Classify a reply text as HOT / WARM / STOP |
| `GET/POST /webhook` | Meta webhook (verify + signed message delivery) |

---

## Local setup

```bash
conda create -n nurturebot python=3.11
conda activate nurturebot
pip install -r requirements.txt

cp .env.example .env        # fill in your own values — see .env.example for the full list
python setup_sheets.py      # create the Google Sheet tabs
python seed_demo.py         # add 3 demo leads

uvicorn main:app --reload --host 0.0.0.0 --port 8007
streamlit run streamlit_app/app.py  # http://localhost:8501
pytest                      # run the test suite
```

**Required:** a Google service-account `credentials.json` (never commit it), a Groq API key, and a Meta WhatsApp Cloud API app.

### Useful scripts

| Script | Purpose |
|---|---|
| `setup_sheets.py` | Create the 3 sheet tabs with headers |
| `seed_demo.py` / `reset_demo.py` | Add / reset the 3 demo leads |
| `run_daily.py [--dry-run]` | Run the daily send locally |
| `preview_messages.py` | Print today's AI messages without sending |
| `simulate_reply.py <name> "<text>"` | Simulate a buyer reply |

---

## Demo mode vs live mode

| | Demo mode (`DEMO_MODE=true`) | Live mode (`DEMO_MODE=false`) |
|---|---|---|
| Recipient | All messages go to the demo number | Each lead's real number |
| Message type | Free-form text (24h window) | Approved Meta template `nurture_followup` |
| Reply matching | Only replies made with WhatsApp **Reply** (reply-to) | Reply-to, or sender phone |

**Live mode template** (`nurture_followup`, language `en`, category Marketing):

```
Hi {{1}}, a quick follow-up on your textile sourcing enquiry.

{{2}}

Reply STOP if you'd prefer not to receive further messages.
```

Set `WA_NURTURE_TEMPLATE=nurture_followup` and `WA_TEMPLATE_LANG=en` once Meta approves it.

---

## Deployment

- **API + dashboard:** two Render web services (free tier sleeps after 15 min; the daily job wakes it first).
- **Schedule:** `.github/workflows/nurturebot-daily.yml` — runs daily at 04:00 UTC (9 AM PKT) and can be triggered manually. Needs repo secrets `NURTUREBOT_URL` and `NURTUREBOT_API_KEY`.
- **Replies:** the Meta webhook points to the n8n router, which forwards every message to `/incoming` before the Order Agent.

---

## Security

- Secrets live only in Render environment variables, GitHub Actions secrets and a local `.env` — never in the repo.
- Meta webhook requests are verified with the app-secret signature.
- Dashboard is password-protected; all write endpoints need `X-API-Key`.

---

## Demo

📹 _Demo video: coming soon_

---

Built by **M. Junaid Iqbal** — AI Automation Engineer for textile exporters & Pakistani D2C brands.
[iamjunaidiqbal.com](https://iamjunaidiqbal.com) · [LinkedIn](https://linkedin.com/in/m-junaid-iqbal-5644b882)
