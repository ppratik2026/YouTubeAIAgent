"""Is everything all right? One list of problems, worst first - for ./yt health and the dashboard.
level: error = nothing will happen until you fix it, warn = something is degraded."""
import shutil
from datetime import datetime, timezone

from . import llm, settings, state, tts, youtube
from .util import read_json, write_json

HEARTBEAT = settings.SHARED_DIR / "heartbeat.json"
LOGIN_CACHE = settings.DATA_DIR / "login_check.json"


def beat():
    """The worker calls this every loop; the dashboard reads it to know the worker is alive."""
    write_json(HEARTBEAT, {"at": datetime.now(timezone.utc).isoformat()})


def _age_minutes(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60


def _login_ok():
    """Refreshing the token costs no quota; still, check at most once an hour."""
    c = read_json(LOGIN_CACHE, {})
    if c.get("at") and _age_minutes(c["at"]) < 60:
        return c["ok"], c.get("error", "")
    try:
        youtube.access_token()
        ok, err = True, ""
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)[:200]
    write_json(LOGIN_CACHE, {"at": datetime.now(timezone.utc).isoformat(), "ok": ok, "error": err})
    return ok, err


def check(worker_expected=True):
    out = []

    def add(level, msg):
        out.append({"level": level, "msg": msg})

    total, _, free = shutil.disk_usage(settings.SHARED_DIR)
    pct = free * 100 / total
    if pct < 8:
        add("error", f"Disk almost full ({pct:.0f}% free, {free // 2**30} GB). Videos will fail - lower "
                     "KEEP_UPLOADED_DAYS or delete old data/videos.")
    elif pct < 20:
        add("warn", f"Disk {pct:.0f}% free ({free // 2**30} GB).")

    hb = read_json(HEARTBEAT, {})
    if worker_expected and (not hb.get("at") or _age_minutes(hb["at"]) > 90):
        add("error", "The worker is not running (no heartbeat for 90+ min). docker compose up -d")

    if settings.LLM_PROVIDER == "gemini" and not settings.GEMINI_API_KEY:
        add("error", "GEMINI_API_KEY missing in .env - no scripts can be written.")
    elif settings.GEMINI_DAILY_LIMIT and llm.calls_today() >= settings.GEMINI_DAILY_LIMIT:
        add("warn", "Gemini free quota used up for today - paused until Google's reset (midnight US Pacific).")
    if not settings.PEXELS_API_KEY and not settings.VISUALS_OFFLINE:
        add("warn", "PEXELS_API_KEY missing - stock footage off, AI images and plain backgrounds only.")

    if youtube.configured():
        ok, err = _login_ok()
        if not ok:
            add("error", f"YouTube login failed - run scripts/get_refresh_token.py again. ({err})")
    elif settings.AUTO_UPLOAD:
        add("warn", "YouTube not connected - videos are made but not uploaded.")

    hist = state.history()
    failed_up = [e for e in hist if e["status"] == "upload_failed"]
    if failed_up:
        add("error", f"{len(failed_up)} upload(s) failed, last: {failed_up[-1].get('error', '')[:150]}")
    held = sum(1 for e in hist if e["status"] == "review")
    if held >= 5:
        add("warn", f"{held} videos waiting in review - approve or reject them.")
    for j in state.jobs():
        if j["status"] == "stopped":
            add("error", f"Job {j['id']} ({j['category']}) stopped after {j['failed']} failures - see the log.")
        elif j["status"] == "active" and j["failed"] >= 3 and j["failed"] > j["made"]:
            add("warn", f"Job {j['id']} ({j['category']}) fails more than it succeeds ({j['failed']} failed).")

    if settings.TTS_PROVIDER == "clone" or any(j.get("tts") == "clone" for j in state.jobs() if j["status"] == "active"):
        if tts.pick_engine("clone", "male") != "clone" and tts.pick_engine("clone", "female") != "clone":
            add("warn", "Voice clone requested but the voice service is not ready - free voice is used instead.")

    out.sort(key=lambda p: 0 if p["level"] == "error" else 1)
    return out
