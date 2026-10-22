"""Event calendar: queue videos ahead of festivals and other dated events (config/calendar.json), so
they are made, uploaded and live a few days before people start searching."""
import json
from datetime import date, timedelta

from . import settings, state
from .util import log, read_json, write_json

DONE = settings.DATA_DIR / "calendar_done.json"


def events():
    p = settings.ROOT / "config" / "calendar.json"
    return json.loads(p.read_text(encoding="utf-8")).get("events", []) if p.exists() else []


def _for_this_channel(ev):
    chans = ev.get("channels") or ["*"]
    return "*" in chans or (settings.CHANNEL and settings.CHANNEL in chans)


def queue_due(today=None):
    """Add a job for every event whose lead time has started and that this channel has not queued yet."""
    today = today or date.today()
    done = read_json(DONE, [])
    added = 0
    for ev in events():
        key = f"{ev['name']}|{ev['date']}"
        if key in done or not _for_this_channel(ev):
            continue
        day = date.fromisoformat(ev["date"])
        if day - timedelta(days=int(ev.get("lead_days", 5))) <= today <= day:
            ch = settings.load_channel()
            job = state.add_job(ev.get("category", "devotional"), ev.get("language") or ch.get("language", "hi"),
                                ev.get("format", "short"), int(ev.get("count", 1)), topic=ev.get("topic", ev["name"]),
                                event=ev["name"], edit=ev.get("edit"), style=ev.get("style"))
            done.append(key)
            added += 1
            log.info("calendar: queued %s (%s) for %s", ev["name"], job["id"], ev["date"])
        elif today > day:
            done.append(key)  # missed: never queue a festival video after the festival
    write_json(DONE, done)
    return added


def upcoming(days=60, today=None):
    today = today or date.today()
    return [ev for ev in events() if _for_this_channel(ev)
            and today <= date.fromisoformat(ev["date"]) <= today + timedelta(days=days)]
