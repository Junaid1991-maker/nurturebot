"""HOT alerts to Junaid: email (Gmail SMTP + App Password, same as LeadHunterBot
integrations/email_sender.py) and WhatsApp (only reaches you if YOUR number messaged
the business number in the last 24 hours)."""
import smtplib
from email.message import EmailMessage

import config


def make_email_sender():
    if not (config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD):
        return None

    def send(to: str, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.GMAIL_ADDRESS, to, subject
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD.replace(" ", ""))
            s.send_message(msg)
        return "email-sent"
    return send


def hot_alert_text(lead: dict, reply: str, verdict: dict) -> tuple[str, str]:
    subject = f"🔥 HOT lead: {lead.get('name')} ({lead.get('company')})"
    body = (f"🔥 HOT LEAD — NurtureBot\n\n"
            f"{lead.get('name')} — {lead.get('company')}\n"
            f"Phone: {lead.get('phone')}\n"
            f"Wants: {lead.get('product_interest')} · {lead.get('market')} market\n"
            f"Replied to follow-up Day {lead.get('replied_day', lead.get('day_number'))}\n\n"
            f"Their reply:\n\"{reply}\"\n\n"
            f"Why HOT: {verdict.get('reasoning')} ({verdict.get('source')}, "
            f"confidence {verdict.get('confidence'):.0%})\n\n"
            f"Next step: call or message them today.")
    return subject, body


def send_hot_alert(lead: dict, reply: str, verdict: dict, email_sender, wa_text_sender) -> list[str]:
    subject, body = hot_alert_text(lead, reply, verdict)
    notes = []
    if email_sender and config.ALERT_EMAIL:
        try:
            email_sender(config.ALERT_EMAIL, subject, body)
            notes.append("email alert sent")
        except Exception as e:  # noqa: BLE001
            notes.append(f"email alert FAILED: {str(e)[:80]}")
    if wa_text_sender and config.ALERT_WA_NUMBER:
        try:
            wa_text_sender(config.ALERT_WA_NUMBER, body)
            notes.append("WhatsApp alert sent")
        except Exception as e:  # noqa: BLE001
            notes.append(f"WhatsApp alert FAILED: {str(e)[:80]}")
    return notes or ["no alert channel configured (set GMAIL_* + ALERT_EMAIL in .env)"]
