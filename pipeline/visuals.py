"""One picture or clip per scene, from free sources only.

stock: Pexels video -> Pexels photo -> AI image -> plain background
ai:    AI image (Pollinations -> Cloudflare Workers AI, then once more with a safe rewrite of the
       prompt) -> Pexels photo -> plain background

A blocked or failed image never stops the video: the next source is tried, and the last resort is a
plain background, logged so you can see which scene it was.
"""
import base64
import json
import random
import time
from urllib.parse import quote

from . import settings
from .util import HTTP, download, log, run

PEXELS = "https://api.pexels.com"
STYLES = json.loads((settings.ROOT / "config" / "styles.json").read_text(encoding="utf-8"))


def style_text(name):
    return STYLES.get(name or "", name or "")


def _pexels(path, params):
    if not settings.PEXELS_API_KEY:
        return None
    for _ in range(3):
        r = HTTP.get(PEXELS + path, params=params, headers={"Authorization": settings.PEXELS_API_KEY}, timeout=30)
        if r.status_code == 429:  # free plan: 200 requests per hour
            log.warning("Pexels hourly limit reached, waiting 10 minutes")
            time.sleep(600)
            continue
        if r.status_code != 200:
            log.warning("Pexels %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()
    return None


def pexels_video(query, portrait, used, dest):
    data = _pexels("/videos/search", {"query": query, "per_page": 15,
                                      "orientation": "portrait" if portrait else "landscape"})
    for v in (data or {}).get("videos", []):
        if v["id"] in used or v.get("duration", 0) < 3:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        # Smallest file that is still at least 1080 on the short side; else the biggest there is.
        side = lambda f: min(f["width"], f["height"])  # noqa: E731
        good = sorted([f for f in files if side(f) >= 1080], key=side) or sorted(files, key=side, reverse=True)
        if not good:
            continue
        used.add(v["id"])
        return download(good[0]["link"], dest.with_suffix(".mp4")), "video"
    return None


def pexels_photo(query, portrait, used, dest):
    data = _pexels("/v1/search", {"query": query, "per_page": 15,
                                  "orientation": "portrait" if portrait else "landscape"})
    for p in (data or {}).get("photos", []):
        if p["id"] in used:
            continue
        used.add(p["id"])
        return download(p["src"]["large2x"], dest.with_suffix(".jpg")), "image"
    return None


def pollinations(prompt, portrait, seed, dest):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
           f"?width={w}&height={h}&seed={seed}&nologo=true&enhance=true&model={settings.POLLINATIONS_MODEL}")
    if settings.POLLINATIONS_TOKEN:
        url += f"&token={settings.POLLINATIONS_TOKEN}"
    try:
        out = download(url, dest.with_suffix(".jpg"), timeout=240)
        run(["ffprobe", "-v", "error", str(out)])  # an error page saved as .jpg fails here
        return out, "image"
    except Exception as e:  # noqa: BLE001 - fall through to the next source
        log.warning("Pollinations image failed: %s", str(e)[:200])
        return None


def cloudflare(prompt, portrait, seed, dest):
    """Cloudflare Workers AI, free daily allowance. Square-ish output; render crops it to fit."""
    if not (settings.CF_ACCOUNT_ID and settings.CF_API_TOKEN):
        return None
    url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CF_ACCOUNT_ID}/ai/run/{settings.CF_IMAGE_MODEL}"
    try:
        r = HTTP.post(url, headers={"Authorization": f"Bearer {settings.CF_API_TOKEN}"}, timeout=180,
                      json={"prompt": prompt[:2000], "steps": 8, "seed": seed % 2**31})
        if r.status_code != 200:
            log.warning("Cloudflare image %s: %s", r.status_code, r.text[:200])
            return None
        img = r.json().get("result", {}).get("image")
        if not img:
            return None
        out = dest.with_suffix(".jpg")
        out.write_bytes(base64.b64decode(img))
        return out, "image"
    except Exception as e:  # noqa: BLE001
        log.warning("Cloudflare image failed: %s", str(e)[:200])
        return None


def ai_image(prompt, style, portrait, seed, dest, rewrite=None):
    for attempt in range(2):
        full = f"{prompt}, {style}" if style else prompt
        for source in (pollinations, cloudflare):
            got = source(full, portrait, seed, dest)
            if got:
                return got
        if attempt == 0 and rewrite:
            # Usually a safety block: let the writer reword it (same scene, nothing graphic).
            new = rewrite(prompt)
            if not new or new == prompt:
                break
            log.info("image prompt reworded to: %s", new[:120])
            prompt = new
    return None


def plain(dest, portrait, n):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    colours = ["0x1d3557", "0x2a9d8f", "0x6d597a", "0x264653", "0x9d0208", "0x3a5a40"]
    out = dest.with_suffix(".png")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colours[n % len(colours)]}:s={w}x{h}",
         "-frames:v", "1", str(out)])
    return out, "image"


def test_pattern(dest, portrait, n):
    """Offline tests: a busy picture, so zoom, pan and transitions are visible in the output."""
    w, h = (1080, 1920) if portrait else (1920, 1080)
    out = dest.with_suffix(".jpg")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=1",
         "-vf", f"hue=h={n * 47 % 360}", "-frames:v", "1", str(out)])
    return out, "image"


def for_scene(scene, cat, portrait, used, dest, n, seed, rewrite=None):
    if settings.VISUALS_OFFLINE:
        return test_pattern(dest, portrait, n)
    query = scene.get("visual_query") or "abstract background"
    prompt = scene.get("image_prompt") or query
    style = style_text(cat.get("style"))
    if cat.get("visuals") == "ai":
        order = [lambda: ai_image(prompt, style, portrait, seed + n, dest, rewrite),
                 lambda: pexels_photo(query, portrait, used, dest)]
    else:
        order = [lambda: pexels_video(query, portrait, used, dest),
                 lambda: pexels_photo(query, portrait, used, dest),
                 lambda: ai_image(prompt, style or style_text("realistic"), portrait, seed + n, dest, rewrite)]
    for fn in order:
        got = fn()
        if got:
            return got
    log.warning("no visual for scene %s (%s), using a plain background", n, query)
    return plain(dest, portrait, n)


def new_seed():
    return random.randint(1, 10_000_000)
