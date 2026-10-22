import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import settings

log = logging.getLogger("yt")

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) YouTubeAIAgent/1.0"


def setup_logging():
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_DIR / "pipeline.log", encoding="utf-8"),
    ])


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(text, n=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].strip("-") or "video")


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        log.warning("could not read %s, starting fresh", path)
        return default


def write_json(path, data):
    """Atomic write, so a crash mid-write never leaves a half file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def retry(fn, tries=3, wait=5, what="request"):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - every failure here is retried the same way
            if i == tries - 1:
                raise
            log.warning("%s failed (%s), retrying in %ss", what, e, wait * (i + 1))
            time.sleep(wait * (i + 1))


def run(cmd):
    """Run ffmpeg/ffprobe; on failure show the tail of stderr, which is where ffmpeg explains."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def download(url, dest, timeout=120):
    def go():
        with HTTP.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    fh.write(chunk)
        if Path(dest).stat().st_size < 1000:
            raise RuntimeError("download too small")
        return dest
    return retry(go, what=f"download {url[:60]}")
