"""All configuration comes from environment variables (or a .env file next to the repo root).

Everything the app writes lives under DATA_DIR, so moving to another server is: copy .env and the
data folder, then start the container again.

Several channels: each one is a folder data/channels/<name>/ with its own channel.json (identity),
channel.env (its YouTube login and any setting that differs), voices, queue and history. Pick one with
CHANNEL=<name> (the CLI's --channel). What Google counts per project - the YouTube upload quota and
the Gemini free tier - is shared by all channels and lives in the top data folder.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path, override=False):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if override:
            os.environ[k] = v
        else:
            os.environ.setdefault(k, v)


_load_dotenv(ROOT / ".env")
CHANNEL = os.environ.get("CHANNEL", "").strip()
SHARED_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
CHANNELS_DIR = SHARED_DIR / "channels"
if CHANNEL:
    if not (CHANNELS_DIR / CHANNEL).is_dir():
        raise SystemExit(f"no channel '{CHANNEL}' - create it with: ./yt channel-add {CHANNEL}")
    _load_dotenv(CHANNELS_DIR / CHANNEL / "channel.env", override=True)


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_int(name, default):
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


DATA_DIR = CHANNELS_DIR / CHANNEL if CHANNEL else SHARED_DIR
VIDEOS_DIR = DATA_DIR / "videos"
WORK_DIR = DATA_DIR / "work"
LOG_DIR = DATA_DIR / "logs"
for d in (DATA_DIR, VIDEOS_DIR, WORK_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

SKILLS_DIR = ROOT / ".claude" / "skills"
MUSIC_DIR = Path(env("MUSIC_DIR", str(ROOT / "assets" / "music")))

# Script writing. "gemini" (free key from aistudio.google.com) or "offline" for tests.
LLM_PROVIDER = env("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")
# Stay inside the free tier: seconds between calls, and a daily cap (0 = only Google's own limit).
GEMINI_MIN_INTERVAL = float(env("GEMINI_MIN_INTERVAL", "8"))
GEMINI_DAILY_LIMIT = env_int("GEMINI_DAILY_LIMIT", 0)

# Visuals. Free key from pexels.com/api. AI images: Pollinations (no key) and Cloudflare Workers AI
# (free daily allowance, needs a free Cloudflare account id + API token).
PEXELS_API_KEY = env("PEXELS_API_KEY")
POLLINATIONS_TOKEN = env("POLLINATIONS_TOKEN")
POLLINATIONS_MODEL = env("POLLINATIONS_MODEL", "flux")
CF_ACCOUNT_ID = env("CF_ACCOUNT_ID")
CF_API_TOKEN = env("CF_API_TOKEN")
CF_IMAGE_MODEL = env("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
VISUALS_OFFLINE = env("VISUALS_OFFLINE") == "1"

# Voice. "edge" (free Microsoft neural voices), "clone" (your own voice samples through the voice
# service, see voice/), or "offline" for tests.
TTS_PROVIDER = env("TTS_PROVIDER", "edge")
VOICE_SERVER = env("VOICE_SERVER", "http://voice:8000")
VOICES_DIR = DATA_DIR / "voices"
INBOX_DIR = DATA_DIR / "inbox"
for d in (VOICES_DIR, INBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)
# Your own recordings are transcribed with faster-whisper on the CPU (free, offline).
WHISPER_MODEL = env("WHISPER_MODEL", "small")

# Trend research (optional). A YouTube Data API *key* from a separate Google Cloud project, so
# searches do not eat the upload quota.
YOUTUBE_API_KEY = env("YOUTUBE_API_KEY")
REGION = env("REGION", "IN")

# Upload. OAuth client + refresh token from scripts/get_refresh_token.py.
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")
UPLOAD_PRIVACY = env("UPLOAD_PRIVACY", "private")          # private | unlisted | public
UPLOADS_PER_DAY = env_int("UPLOADS_PER_DAY", 6)            # default YouTube quota fits ~6
PUBLISH_GAP_HOURS = env_int("PUBLISH_GAP_HOURS", 0)        # >0: schedule public at this spacing
AUTO_UPLOAD = env("AUTO_UPLOAD", "1") == "1"
KEEP_UPLOADED_DAYS = env_int("KEEP_UPLOADED_DAYS", 7)

# Rendering
VIDEO_CRF = env_int("VIDEO_CRF", 21)
X264_PRESET = env("X264_PRESET", "veryfast")
FPS = env_int("FPS", 30)
CHANNEL_FOOTER = env("CHANNEL_FOOTER")
WORKER_SLEEP_SECONDS = env_int("WORKER_SLEEP_SECONDS", 300)


def load_categories():
    return json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))


def load_channel():
    for p in (DATA_DIR / "channel.json", ROOT / "config" / "channel.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def channels():
    return sorted(p.name for p in CHANNELS_DIR.glob("*") if (p / "channel.json").exists())
