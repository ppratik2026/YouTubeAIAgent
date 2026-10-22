"""One function: ask the model for JSON. Gemini's free tier by default; "offline" returns the
caller's canned answer so the whole pipeline can be tested without any key."""
import json
import re
import time

from . import settings
from .util import HTTP, log

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


def _parse(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def _gemini(prompt, system, temperature):
    if not settings.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set (free key: https://aistudio.google.com)")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    for attempt in range(6):
        r = HTTP.post(url, params={"key": settings.GEMINI_API_KEY}, json=body, timeout=180)
        if r.status_code in (429, 500, 503):
            # Free tier is rate limited per minute; back off instead of failing the video.
            wait = 20 * (attempt + 1)
            log.warning("Gemini %s, waiting %ss", r.status_code, wait)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise LLMError(f"Gemini {r.status_code}: {r.text[:400]}")
        data = r.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise LLMError(f"Gemini returned no text: {json.dumps(data)[:400]}")
        try:
            return _parse(text)
        except ValueError:
            log.warning("Gemini returned invalid JSON, asking again")
    raise LLMError("Gemini kept failing")


def ask_json(prompt, system, offline, temperature=0.9):
    """offline: a callable that returns the canned answer for LLM_PROVIDER=offline."""
    if settings.LLM_PROVIDER == "offline":
        return offline()
    if settings.LLM_PROVIDER == "gemini":
        return _gemini(prompt, system, temperature)
    raise LLMError(f"unknown LLM_PROVIDER {settings.LLM_PROVIDER!r}")
