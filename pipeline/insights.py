"""Learn from your own channel and track the road to monetization.

- refresh_stats: views/likes/comments of uploaded videos (YouTube Data API, ~1 quota unit per 50 videos)
- performance_block: what worked and what did not on THIS channel, fed into the next topic choice
- progress: subscribers, public watch hours (12 months) and Shorts views (90 days) vs the YPP bar
"""
from datetime import date, datetime, timedelta, timezone

from . import state, youtube
from .util import HTTP, log, now_iso

REFRESH_HOURS = 12
# YouTube Partner Program, ads tier, as published for 2026. Check YouTube's help page; it changes.
YPP = {"subscribers": 1000, "watch_hours": 4000, "shorts_views_90d": 10_000_000}


def _age_hours(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def refresh_stats():
    if not youtube.configured():
        return
    due = [e for e in state.history() if e.get("youtube_id")
           and (not e.get("stats_at") or _age_hours(e["stats_at"]) >= REFRESH_HOURS)]
    if not due:
        return
    token = youtube.access_token()
    for i in range(0, len(due), 50):
        batch = due[i:i + 50]
        r = HTTP.get("https://www.googleapis.com/youtube/v3/videos", timeout=30,
                     params={"part": "statistics", "id": ",".join(e["youtube_id"] for e in batch)},
                     headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            log.warning("stats refresh failed %s: %s", r.status_code, r.text[:200])
            return
        got = {v["id"]: v["statistics"] for v in r.json().get("items", [])}
        for e in batch:
            st = got.get(e["youtube_id"], {})
            state.update_history(e["id"], views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)),
                                 comments=int(st.get("commentCount", 0)), stats_at=now_iso())


def performance_block(category, video_format):
    """Top and bottom videos of this category by views per day (videos older than 2 days)."""
    rows = []
    for e in state.history():
        if e["category"] != category or e["format"] != video_format or "views" not in e:
            continue
        days = _age_hours(e["uploaded_at"]) / 24 if e.get("uploaded_at") else 0
        if days >= 2:
            rows.append((e["views"] / days, e))
    if len(rows) < 4:
        return ""
    rows.sort(key=lambda r: -r[0])

    def line(r):
        e = r[1]
        return f"- {e['title']} ({r[0]:.0f} views/day; hook: {e.get('formula', '?')}; shape: {e.get('structure', '?')})"
    top = "\n".join(line(r) for r in rows[:5])
    bottom = "\n".join(line(r) for r in rows[-3:])
    return (f"On THIS channel these did best - make more like them (topic type, hook, shape):\n{top}\n"
            f"These did worst - avoid what they have in common:\n{bottom}\n\n")


def _analytics(token, start, metrics, dims=None):
    params = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": date.today().isoformat(),
              "metrics": metrics}
    if dims:
        params["dimensions"] = dims
    r = HTTP.get("https://youtubeanalytics.googleapis.com/v2/reports", params=params, timeout=30,
                 headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json().get("rows", [])


def progress():
    if not youtube.configured():
        return "YouTube not connected (.env YT_* missing)"
    token = youtube.access_token()
    r = HTTP.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet,statistics", "mine": "true"},
                 headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    ch = r.json()["items"][0]
    subs = int(ch["statistics"].get("subscriberCount", 0))
    out = [f"Channel: {ch['snippet']['title']}",
           f"Subscribers:        {subs:>10,} / {YPP['subscribers']:,}  ({min(100, subs * 100 // YPP['subscribers'])}%)"]
    try:
        # creatorContentType splits long videos from Shorts; Shorts-feed watch time does not count for YPP.
        rows = _analytics(token, date.today() - timedelta(days=365), "estimatedMinutesWatched", "creatorContentType")
        minutes = sum(m for t, m in rows if t.upper() in ("VIDEO_ON_DEMAND", "VIDEOONDEMAND", "LIVE_STREAM", "LIVESTREAM"))
        hours = int(minutes / 60)
        out.append(f"Watch hours (12 mo): {hours:>10,} / {YPP['watch_hours']:,}  ({min(100, hours * 100 // YPP['watch_hours'])}%)"
                   "  long videos only, approx.")
        rows = _analytics(token, date.today() - timedelta(days=90), "views", "creatorContentType")
        shorts = int(sum(v for t, v in rows if t.upper() == "SHORTS"))
        out.append(f"Shorts views (90 d): {shorts:>10,} / {YPP['shorts_views_90d']:,}  "
                   f"({min(100, shorts * 100 // YPP['shorts_views_90d'])}%)")
    except Exception as e:  # noqa: BLE001
        out.append(f"Watch hours: not available ({e}). Run scripts/get_refresh_token.py again - "
                   "it now asks for YouTube Analytics (read-only) too.")
    out.append("Needs subscribers AND (watch hours OR Shorts views). Then apply in YouTube Studio -> Earn.")
    return "\n".join(out)
