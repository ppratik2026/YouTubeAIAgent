"""The queue, the history of every video, and today's upload count - three JSON files in DATA_DIR.
A file lock keeps the CLI and the worker from overwriting each other."""
import fcntl
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from . import settings
from .util import now_iso, read_json, write_json

QUEUE = settings.DATA_DIR / "queue.json"
HISTORY = settings.DATA_DIR / "history.json"
QUOTA = settings.DATA_DIR / "quota.json"
LOCK = settings.DATA_DIR / ".lock"


@contextmanager
def locked():
    with open(LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def add_job(category, language, video_format, count, minutes, voice):
    job = {"id": uuid.uuid4().hex[:8], "category": category, "language": language, "format": video_format,
           "count": count, "minutes": minutes, "voice": voice, "made": 0, "failed": 0,
           "status": "active", "created": now_iso()}
    with locked():
        q = read_json(QUEUE, {"jobs": []})
        q["jobs"].append(job)
        write_json(QUEUE, q)
    return job


def jobs():
    return read_json(QUEUE, {"jobs": []})["jobs"]


def next_job():
    for j in jobs():
        if j["status"] == "active" and j["made"] < j["count"]:
            return j
    return None


def update_job(job_id, **changes):
    with locked():
        q = read_json(QUEUE, {"jobs": []})
        for j in q["jobs"]:
            if j["id"] == job_id:
                for k, v in changes.items():
                    j[k] = j.get(k, 0) + v if k in ("made", "failed") else v
                if j["made"] >= j["count"]:
                    j["status"] = "done"
                if j["failed"] >= max(5, j["count"]):  # stop a job that only ever fails
                    j["status"] = "stopped"
        write_json(QUEUE, q)


def history():
    return read_json(HISTORY, [])


def add_history(entry):
    with locked():
        h = read_json(HISTORY, [])
        h.append(entry)
        write_json(HISTORY, h)


def update_history(video_id, **changes):
    with locked():
        h = read_json(HISTORY, [])
        for e in h:
            if e["id"] == video_id:
                e.update(changes)
        write_json(HISTORY, h)


def used_titles(category):
    return [t for e in history() if e["category"] == category
            for t in (e.get("source_title"), e.get("topic"), e.get("title")) if t]


def _quota_day():
    # YouTube's daily quota resets at midnight Pacific time.
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def uploads_left():
    q = read_json(QUOTA, {})
    used = q.get("uploads", 0) if q.get("day") == _quota_day() else 0
    return max(0, settings.UPLOADS_PER_DAY - used)


def count_upload(exhausted=False):
    with locked():
        q = read_json(QUOTA, {})
        if q.get("day") != _quota_day():
            q = {"day": _quota_day(), "uploads": 0}
        q["uploads"] = settings.UPLOADS_PER_DAY if exhausted else q["uploads"] + 1
        write_json(QUOTA, q)
