"""Session 2 tests — Groq is faked, no API key needed."""
from fastapi.testclient import TestClient

import main
from nodes.generator import (build_facts, check_output, detect_category,
                             detect_language, generate_message, load_profile)

AHMED = dict(lead_id="NB-1", name="Ahmed Al-Rashid", company="Dubai Laundry Services LLC",
             phone="+971500000001", industry="Hotel/laundry supplies",
             product_interest="Terry towels 500gsm", market="Gulf", day_number=3, notes="DEMO")
SARAH = dict(lead_id="NB-3", name="Sarah Khan", company="Berlin Fashion Imports GmbH",
             phone="+491500000003", industry="Fashion retail", product_interest="Knitwear",
             market="EU", day_number=14, notes="DEMO")
BILAL = dict(lead_id="NB-4", name="Bilal Ahmed", company="Karachi Linen Co", phone="+923001234567",
             industry="Wholesale", product_interest="Bed linen 200TC", market="Other", day_number=7)


def fake_llm(reply):
    calls = []
    def llm(system, user):
        calls.append((system, user))
        return reply
    llm.calls = calls
    return llm


def boom(system, user):
    raise RuntimeError("rate limited")


def test_categories_and_language():
    assert detect_category("Hotel/laundry supplies", "Terry towels 500gsm") == "towels"
    assert detect_category("Wholesale textiles", "Bed linen 200TC") == "bed_linen"
    assert detect_category("Fashion retail", "Knitwear") == "knitwear"
    assert detect_category("", "") == "default"
    assert detect_language("+923001234567") == "roman_urdu_mix"
    assert detect_language("+971500000001") == "english"


def test_all_five_templates_fill_without_ai():
    for day in (3, 7, 14, 21, 30):
        r = generate_message(AHMED, day, llm=None)
        msg = r["personalized_message"]
        assert r["source"] == "template"
        assert "Ahmed" in msg and "{" not in msg and "[" not in msg
    assert generate_message(AHMED, 30)["is_final_message"] is True
    assert generate_message(AHMED, 21)["next_followup_day"] == 30


def test_llm_used_when_output_is_good():
    llm = fake_llm("Salam Ahmed, hope you're well. Many hotel buyers compare towels on GSM and "
                   "absorbency, so consistent weight on repeat orders really matters. Thought it "
                   "might help with your Gulf customers. Let me know if you need anything 🙂")
    r = generate_message(AHMED, 3, llm)
    assert r["source"] == "llm" and r["fallback_reason"] is None
    system, user = llm.calls[0]
    assert "Use ONLY the facts" in system and "simple English" in system
    assert "terry towels 500gsm" in user.lower() and "Ramadan" in user


def test_pakistani_lead_gets_roman_urdu_instruction():
    llm = fake_llm("Salam Bilal bhai, hotel grade bed linen ke liye hum 200TC se upar kaam karte hain. Koi sawal ho toh batayein.")
    generate_message(BILAL, 7, llm)
    assert "Roman Urdu" in llm.calls[0][0]


def test_fallbacks():
    assert generate_message(AHMED, 3, boom)["source"] == "template"
    assert "groq error" in generate_message(AHMED, 3, boom)["fallback_reason"]
    assert generate_message(AHMED, 3, fake_llm("Hi [Name], ..."))["source"] == "template"
    assert generate_message(AHMED, 3, fake_llm("word " * 200))["source"] == "template"
    assert generate_message(AHMED, 3, fake_llm("see https://x.com"))["source"] == "template"
    assert generate_message(AHMED, 3, fake_llm(""))["source"] == "template"


def test_eu_facts_mention_dpp():
    facts = build_facts(SARAH, load_profile())
    assert "Digital Product Passport" in facts["insight"]
    assert "traceability" in facts["capability"]


def test_check_output():
    assert check_output("Hello Ahmed, all good?") is None
    assert check_output("Hi {first_name}") is not None


def test_nurture_endpoint():
    main.app.dependency_overrides[main.get_llm] = lambda: None
    try:
        c = TestClient(main.app)
        r = c.post("/nurture", json={"lead": SARAH})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["day_number"] == 14 and body["next_followup_day"] == 21
        assert "15-minute call" in body["personalized_message"]
        assert c.post("/nurture", json={"lead": SARAH, "day_number": 5}).status_code == 400
    finally:
        main.app.dependency_overrides.clear()
