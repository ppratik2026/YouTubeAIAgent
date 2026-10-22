"""What to make: today's news (Google News RSS, free, no key) and what is working on YouTube in the
category (YouTube Data API key, optional). The YouTube part ranks videos the way /yt-viral does -
by how far each beat the median of the batch - and names the title formula from hooks.json."""
import html
import re
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from . import settings
from .skills import HOOKS
from .util import HTTP, log, retry

EDITIONS = {"hi": "hl=hi&gl=IN&ceid=IN:hi", "en": "hl=en-IN&gl=IN&ceid=IN:en"}


def _rss(url):
    def go():
        r = HTTP.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    root = ET.fromstring(retry(go, what="news rss"))
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        source = it.find("source")
        items.append({
            "title": title,
            "summary": re.sub(r"\s+", " ", desc).strip()[:400],
            "source": source.text if source is not None else "",
            "link": it.findtext("link") or "",
            "published": it.findtext("pubDate") or "",
        })
    return items


def news_stories(query, language, limit=20):
    ed = EDITIONS.get(language, EDITIONS["en"])
    if query:
        url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:2d')}&{ed}"
    else:
        url = f"https://news.google.com/rss?{ed}"
    return _rss(url)[:limit]


def story_facts(story_title, language):
    """Every outlet's headline + snippet on one story: the only facts the script may use."""
    q = re.sub(r"\s+-\s+[^-]+$", "", story_title)  # drop the " - Outlet" suffix
    return news_stories(q, language, limit=8)


def _formula(title):
    best, hits = "Unclassified", 0
    for f in HOOKS["hooks"]:
        n = sum(1 for p in f["match"] if re.search(p, title, re.I))
        if n > hits:
            best, hits = f["name"], n
    return best


def youtube_outliers(category_label, language, video_format, limit=10):
    """Recent popular videos for the category, ranked by multiple over the batch median.
    Costs ~101 quota units on the *key's* project, so use a different project than uploads."""
    if not settings.YOUTUBE_API_KEY:
        return []
    after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"part": "snippet", "q": category_label, "type": "video", "order": "viewCount",
              "maxResults": 25, "publishedAfter": after, "regionCode": settings.REGION,
              "relevanceLanguage": language, "key": settings.YOUTUBE_API_KEY,
              "videoDuration": "short" if video_format == "short" else "medium"}
    try:
        r = HTTP.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=30)
        r.raise_for_status()
        ids = [i["id"]["videoId"] for i in r.json().get("items", [])]
        if not ids:
            return []
        r = HTTP.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
            "part": "snippet,statistics", "id": ",".join(ids), "key": settings.YOUTUBE_API_KEY})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 - research is optional, never block a video on it
        log.warning("YouTube research skipped: %s", e)
        return []
    vids = [{"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
             "views": int(v["statistics"].get("viewCount", 0))} for v in r.json().get("items", [])]
    med = statistics.median([v["views"] for v in vids]) or 1
    for v in vids:
        v["multiple"] = round(v["views"] / med, 2)
        v["formula"] = _formula(v["title"])
    vids.sort(key=lambda v: -v["multiple"])
    return vids[:limit]
