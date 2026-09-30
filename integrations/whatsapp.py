"""Meta WhatsApp Cloud API. Copied from LeadHunterBot integrations/whatsapp.py
(same token, same phone number ID), with clearer error hints added."""
import httpx

import config

HINTS = {
    131047: "outside the 24-hour window: the person must message your WhatsApp number first "
            "(for the demo, send 'Hi' from your phone to the test number)",
    131030: "recipient not in the test number's allowed list (add it in Meta > WhatsApp > API Setup)",
    132001: "template name or language not found / not approved yet",
    190: "access token expired or invalid",
}


def _url() -> str:
    return (f"https://graph.facebook.com/{config.WA_API_VERSION}/"
            f"{config.WA_PHONE_NUMBER_ID}/messages")


def _post(body: dict) -> str:
    r = httpx.post(_url(), json=body, timeout=30,
                   headers={"Authorization": f"Bearer {config.WA_ACCESS_TOKEN}"})
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        code = err.get("code")
        hint = HINTS.get(code, "")
        raise RuntimeError(f"WhatsApp {r.status_code} (code {code}): {err.get('message', r.text)}"
                           f"{' - ' + hint if hint else ''}"[:300])
    return data["messages"][0]["id"]


def configured() -> bool:
    return bool(config.WA_ACCESS_TOKEN and config.WA_PHONE_NUMBER_ID)


def make_wa_text_sender():
    """Free-form text. Meta only delivers it inside the 24-hour window after the
    recipient messaged your business number."""
    if not configured():
        return None

    def send(to: str, text: str) -> str:
        return _post({"messaging_product": "whatsapp", "to": to.lstrip("+"),
                      "type": "text", "text": {"body": text[:4000]}})
    return send


def make_wa_template_sender():
    """Approved template. Works any time, for anyone."""
    if not configured():
        return None

    def send(to: str, template: str, lang: str, params: list[str]) -> str:
        return _post({
            "messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "template",
            "template": {"name": template, "language": {"code": lang},
                         "components": [{"type": "body", "parameters":
                                         [{"type": "text", "text": p} for p in params]}]},
        })
    return send
