"""One function: ask the model for JSON. Gemini's free tier by default; "offline" returns the
caller's canned answer so the whole pipeline can be tested without any key.

Free-tier safety: calls are spaced (GEMINI_MIN_INTERVAL), counted per day (GEMINI_DAILY_LIMIT), and a
429 is waited out using the delay Google sends back. When the day's quota is gone, DailyLimit is
raised and the worker sleeps until Google resets it (midnight Pacific) instead of hammering the key."""
import json
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import settings
from .util import HTTP, log, read_json, write_json

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
COUNTER = settings.SHARED_DIR / "gemini_usage.json"  # one key for all channels
_last_call = [0.0]


class LLMError(RuntimeError):
    pass


class DailyLimit(LLMError):
    """The free daily quota is used up; try again after the reset."""


def _parse(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def _today():
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def calls_today():
    c = read_json(COUNTER, {})
    return c.get("calls", 0) if c.get("day") == _today() else 0


def _count(exhausted=False):
    c = read_json(COUNTER, {})
    if c.get("day") != _today():
        c = {"day": _today(), "calls": 0}
    c["calls"] = settings.GEMINI_DAILY_LIMIT if exhausted else c["calls"] + 1
    write_json(COUNTER, c)


def _retry_delay(resp):
    """Google puts the wait in error.details[RetryInfo].retryDelay, e.g. "37s"."""
    try:
        for d in resp.json()["error"].get("details", []):
            if "retryDelay" in d:
                return float(d["retryDelay"].rstrip("s")) + 2
    except (ValueError, KeyError, AttributeError):
        pass
    return None


def _gemini(prompt, system, temperature):
    if not settings.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set (free key: https://aistudio.google.com)")
    if settings.GEMINI_DAILY_LIMIT and calls_today() >= settings.GEMINI_DAILY_LIMIT:
        raise DailyLimit(f"{calls_today()} Gemini calls today (GEMINI_DAILY_LIMIT)")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    bad_json = 0
    for attempt in range(8):
        wait = settings.GEMINI_MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        r = HTTP.post(url, headers={"x-goog-api-key": settings.GEMINI_API_KEY}, json=body, timeout=300)
        _count()
        if r.status_code == 429:
            text = r.text
            if "PerDay" in text or "per day" in text.lower():
                _count(exhausted=True)
                raise DailyLimit("Gemini free daily quota used up")
            delay = _retry_delay(r) or 30 * (attempt + 1)
            log.warning("Gemini per-minute limit, waiting %.0fs", delay)
            time.sleep(delay)
            continue
        if r.status_code in (500, 502, 503, 504):
            log.warning("Gemini %s (busy), waiting %ss", r.status_code, 20 * (attempt + 1))
            time.sleep(20 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise LLMError(f"Gemini {r.status_code}: {r.text[:400]}")
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            # Blocked by Gemini's safety filter or empty: say why instead of a vague crash.
            raise LLMError(f"Gemini returned nothing (finishReason={cand.get('finishReason')}, "
                           f"promptFeedback={data.get('promptFeedback')})")
        try:
            return _parse(text)
        except ValueError:
            bad_json += 1
            if bad_json >= 2:
                raise LLMError("Gemini returned invalid JSON twice")
            log.warning("Gemini returned invalid JSON, asking again")
    raise LLMError("Gemini kept failing")


def ask_json(prompt, system, offline, temperature=0.9):
    """offline: a callable that returns the canned answer for LLM_PROVIDER=offline."""
    if settings.LLM_PROVIDER == "offline":
        return offline()
    if settings.LLM_PROVIDER == "gemini":
        return _gemini(prompt, system, temperature)
    raise LLMError(f"unknown LLM_PROVIDER {settings.LLM_PROVIDER!r}")
