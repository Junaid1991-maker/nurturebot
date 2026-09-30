"""Groq wrapper. Returns a simple callable llm(system, user) -> str, or None if no key."""
from typing import Callable, Optional

import config

LLM = Callable[[str, str], str]


def make_groq_llm(json_mode: bool = False) -> Optional[LLM]:
    if not config.GROQ_API_KEY:
        return None
    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY, timeout=30.0, max_retries=2)

    def call(system: str, user: str) -> str:
        kwargs = dict(
            model=config.GROQ_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.7,
            max_completion_tokens=1024,   # gpt-oss counts its reasoning inside this budget
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["temperature"] = 0.1
        if "gpt-oss" in config.GROQ_MODEL:
            kwargs["reasoning_effort"] = "low"
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    return call
