"""One picture or clip per scene.

stock: Pexels video -> Pexels photo -> AI image -> plain background
ai:    AI image (Pollinations, free, no key) -> Pexels photo -> plain background
"""
import random
import time
from urllib.parse import quote

from . import settings
from .util import HTTP, download, log, run

PEXELS = "https://api.pexels.com"


def _pexels(path, params):
    if not settings.PEXELS_API_KEY:
        return None
    for attempt in range(3):
        r = HTTP.get(PEXELS + path, params=params, headers={"Authorization": settings.PEXELS_API_KEY}, timeout=30)
        if r.status_code == 429:  # free plan: 200 requests per hour
            log.warning("Pexels rate limit, waiting 10 minutes")
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


def ai_image(prompt, style, portrait, seed, dest):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    full = f"{prompt}, {style}" if style else prompt
    url = (f"https://image.pollinations.ai/prompt/{quote(full[:900])}"
           f"?width={w}&height={h}&seed={seed}&nologo=true&model=flux")
    if settings.POLLINATIONS_TOKEN:
        url += f"&token={settings.POLLINATIONS_TOKEN}"
    try:
        return download(url, dest.with_suffix(".jpg"), timeout=180), "image"
    except Exception as e:  # noqa: BLE001 - fall through to the next source
        log.warning("AI image failed: %s", e)
        return None


def plain(dest, portrait, n):
    w, h = (1080, 1920) if portrait else (1920, 1080)
    colours = ["0x1d3557", "0x2a9d8f", "0x6d597a", "0x264653", "0x9d0208", "0x3a5a40"]
    out = dest.with_suffix(".png")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colours[n % len(colours)]}:s={w}x{h}",
         "-frames:v", "1", str(out)])
    return out, "image"


def for_scene(scene, cat, portrait, used, dest, n, seed):
    if settings.VISUALS_OFFLINE:
        return plain(dest, portrait, n)
    query = scene.get("visual_query") or "abstract background"
    prompt = scene.get("image_prompt") or query
    if cat.get("visuals") == "ai":
        order = [lambda: ai_image(prompt, cat.get("ai_style", ""), portrait, seed + n, dest),
                 lambda: pexels_photo(query, portrait, used, dest)]
    else:
        order = [lambda: pexels_video(query, portrait, used, dest),
                 lambda: pexels_photo(query, portrait, used, dest),
                 lambda: ai_image(prompt, "realistic photo", portrait, seed + n, dest)]
    for fn in order:
        got = fn()
        if got:
            return got
    log.warning("no visual for scene %s (%s), using a plain background", n, query)
    return plain(dest, portrait, n)


def new_seed():
    return random.randint(1, 10_000_000)
