"""Comment replies, following the yt-comment skill: triage into question / correction / praise / bait,
a short reply in the channel's voice for the first three, nothing for bait. Replies wait for your
approval (./yt comments, or the dashboard) unless COMMENTS_AUTO_REPLY=1.

Quota: reading is ~1 unit per call, posting a reply is 50 units out of the same daily 10,000 as uploads,
so posting stops at COMMENTS_PER_DAY."""
from datetime import datetime, timezone

from . import settings, state, youtube
from .llm import ask_json
from .skills import rules
from .util import HTTP, log, now_iso, read_json, write_json

FILE = settings.DATA_DIR / "comments.json"
API = "https://www.googleapis.com/youtube/v3"
FETCH_HOURS = 6


def _load():
    return read_json(FILE, {"fetched_at": None, "items": {}, "posted_today": {"day": "", "n": 0}})


def _save(d):
    with state.locked():
        write_json(FILE, d)


def _due(d):
    if not d["fetched_at"]:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])).total_seconds() > FETCH_HOURS * 3600


def fetch_and_draft(force=False):
    """New top-level comments on our uploads that nobody from the channel has answered yet."""
    if not youtube.configured():
        return 0
    d = _load()
    if not (force or _due(d)):
        return 0
    token = youtube.access_token()
    videos = {e["youtube_id"]: e for e in state.history() if e.get("youtube_id")}
    new = []
    for vid, e in list(videos.items())[-30:]:  # recent uploads; older ones rarely get new comments
        r = HTTP.get(f"{API}/commentThreads", timeout=30, headers={"Authorization": f"Bearer {token}"},
                     params={"part": "snippet", "videoId": vid, "maxResults": 50, "order": "time",
                             "textFormat": "plainText"})
        if r.status_code != 200:
            log.warning("comments for %s: %s %s", vid, r.status_code, r.text[:150])
            continue
        for th in r.json().get("items", []):
            sn = th["snippet"]
            top = sn["topLevelComment"]["snippet"]
            if th["id"] in d["items"] or sn.get("totalReplyCount", 0) > 0:
                continue
            if top.get("authorChannelId", {}).get("value") == sn.get("channelId"):
                continue  # our own comment
            new.append({"id": th["id"], "video": vid, "video_title": e["title"], "author": top["authorDisplayName"],
                        "text": top["textDisplay"][:600], "likes": top.get("likeCount", 0)})
    if not new:
        d["fetched_at"] = now_iso()
        _save(d)
        return 0
    drafted = draft(new)
    for c in new:
        c.update(drafted.get(c["id"], {"pile": "question", "reply": ""}))
        c["status"] = "skipped" if c["pile"] == "bait" or not c["reply"] else "draft"
        c["at"] = now_iso()
        d["items"][c["id"]] = c
    d["fetched_at"] = now_iso()
    _save(d)
    log.info("comments: %d new, %d replies drafted", len(new), sum(1 for c in new if c["status"] == "draft"))
    if settings.env("COMMENTS_AUTO_REPLY") == "1":
        for c in new:
            if c["status"] == "draft" and c["pile"] in ("question", "praise"):
                approve(c["id"])
        post_approved()
    return len(new)


def draft(items):
    ch = settings.load_channel()
    host = (ch.get("host") or {}).get("name", "")
    listing = "\n".join(f"{c['id']} | video: {c['video_title'][:60]} | {c['author']}: {c['text']}" for c in items)
    out = ask_json(
        f"{rules('yt-comment')}\n\nChannel: {ch.get('name', '')} ({ch.get('niche', '')}). Replies are written "
        f"as the host{(' ' + host) if host else ''}, in the same language the commenter used.\n\n"
        f"Comments (id | video | author: text):\n{listing}\n\n"
        'For EVERY comment: {"id": "...", "pile": "question|correction|praise|bait", "reply": "under 30 '
        'words, empty for bait", "pin": false}. Mark at most one pin: true (the question most people also have).\n'
        'JSON: {"comments": [...]}',
        "You manage a YouTube creator's comment section. Reply with JSON only.", temperature=0.6,
        offline=lambda: {"comments": [{"id": c["id"], "pile": "praise", "reply": "Thank you!", "pin": False}
                                      for c in items]})
    return {c["id"]: {"pile": c.get("pile", "question"), "reply": c.get("reply", "").strip(),
                      "pin": bool(c.get("pin"))} for c in out.get("comments", []) if c.get("id")}


def pending():
    return [c for c in _load()["items"].values() if c["status"] == "draft"]


def approve(cid, text=None):
    d = _load()
    c = d["items"].get(cid)
    if not c:
        return False
    if text:
        c["reply"] = text
    c["status"] = "approved"
    _save(d)
    return True


def skip(cid):
    d = _load()
    if cid in d["items"]:
        d["items"][cid]["status"] = "skipped"
        _save(d)


def post_approved():
    if not youtube.configured():
        return 0
    d = _load()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if d["posted_today"]["day"] != today:
        d["posted_today"] = {"day": today, "n": 0}
    limit = settings.env_int("COMMENTS_PER_DAY", 20)
    token, done = None, 0
    for c in [c for c in d["items"].values() if c["status"] == "approved"]:
        if d["posted_today"]["n"] >= limit:
            break
        token = token or youtube.access_token()
        r = HTTP.post(f"{API}/comments", params={"part": "snippet"}, timeout=30,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"snippet": {"parentId": c["id"], "textOriginal": c["reply"]}})
        if r.status_code == 200:
            c["status"], c["posted_at"] = "posted", now_iso()
            d["posted_today"]["n"] += 1
            done += 1
        elif r.status_code == 403 and "insufficient" in r.text.lower():
            log.warning("posting replies needs the youtube.force-ssl permission - run "
                        "scripts/get_refresh_token.py again")
            break
        else:
            c["status"], c["error"] = "failed", r.text[:200]
    _save(d)
    return done
