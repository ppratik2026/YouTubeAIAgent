"""One job step = one finished video folder: video.mp4, thumbnail.jpg, meta.json."""
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from . import render, settings, state, tts, visuals, writer, youtube
from .util import log, now_iso, slug, write_json


def category(name):
    cats = settings.load_categories()
    if name in cats:
        return dict(cats[name], key=name)
    # Any category the user types works: treated as an original-content explainer with stock footage.
    return {"key": name, "label": name, "visuals": "stock", "news": False, "mood": "neutral",
            "youtube_category": "22", "tone": f"An original, engaging video in the '{name}' category."}


def make_video(job):
    cat = category(job["category"])
    lang, fmt = job["language"], job["format"]
    portrait = fmt == "short"
    vid_id = uuid.uuid4().hex[:8]
    work = settings.WORK_DIR / vid_id
    work.mkdir(parents=True, exist_ok=True)
    log.info("== %s %s %s video (job %s) ==", cat["label"], lang, fmt, job["id"])

    topic = writer.pick_topic(cat, lang, fmt, state.used_titles(job["category"]))
    log.info("topic: %s", topic["topic"])
    hook = writer.best_hook(cat, lang, fmt, topic)[0]
    script = (writer.write_short(cat, lang, topic, hook) if portrait
              else writer.write_long(cat, lang, topic, hook, job.get("minutes") or 8))
    meta = writer.package(cat, lang, fmt, topic, script)

    scenes, starts, used, seed = [], [], set(), visuals.new_seed()
    gender = job.get("voice") or "male"
    for sec in script["sections"]:
        starts.append((sec["heading"], len(scenes)))
        for sc in sec["scenes"]:
            n = len(scenes)
            sc["audio"] = tts.speak(sc["narration"], work / f"s{n:03d}.mp3", lang, gender, cat["mood"])
            sc["visual"], sc["kind"] = visuals.for_scene(sc, cat, portrait, used, work / f"img{n:03d}", n, seed)
            scenes.append(sc)
    if len(scenes) < 3:
        raise RuntimeError(f"script too short ({len(scenes)} scenes)")

    out = settings.VIDEOS_DIR / f"{datetime.now():%Y%m%d-%H%M}-{slug(meta['title'])}-{vid_id}"
    out.mkdir(parents=True)
    total = render.render(scenes, lang, portrait, cat["mood"], work, out / "video.mp4")

    desc = [meta["description"]]
    if not portrait:
        ch = render.chapters([(h, scenes[i]["start"]) for h, i in starts], total)
        if ch:
            desc.append(ch)
        render.thumbnail(work / "v000.mp4", meta["thumb_text"] or meta["title"], lang, out / "thumbnail.jpg", work)
    if topic["facts"]:
        desc.append("Sources: " + ", ".join(sorted({f["source"] for f in topic["facts"] if f["source"]})))
    if any(s["kind"] == "video" for s in scenes) or cat.get("visuals") == "stock":
        desc.append("Stock footage: Pexels")
    if settings.CHANNEL_FOOTER:
        desc.append(settings.CHANNEL_FOOTER)

    meta.update(description="\n\n".join(d for d in desc if d).strip(), language=lang,
                category_id=cat["youtube_category"], duration=round(total, 1), hook=hook["text"],
                hook_score=hook["score"]["verdict"], topic=topic["topic"])
    (out / "script.txt").write_text("\n\n".join(
        f"## {sec['heading']}\n" + "\n".join(s["narration"] for s in sec["scenes"]) for sec in script["sections"]),
        encoding="utf-8")
    write_json(out / "meta.json", meta)
    shutil.rmtree(work, ignore_errors=True)

    entry = {"id": vid_id, "job": job["id"], "category": job["category"], "language": lang, "format": fmt,
             "topic": topic["topic"], "source_title": topic.get("source_title", ""), "title": meta["title"],
             # dir is relative, so data/ can move to another server
             "dir": out.name, "made_at": now_iso(), "status": "ready", "duration": meta["duration"]}
    state.add_history(entry)
    log.info("made %s (%.0fs) -> %s", meta["title"], total, out)
    return entry


def upload_ready():
    """Upload finished videos, oldest first, as far as today's quota allows."""
    if not (settings.AUTO_UPLOAD and youtube.configured()):
        return 0
    done = 0
    for e in [e for e in state.history() if e["status"] == "ready"]:
        if state.uploads_left() <= 0:
            break
        folder = settings.VIDEOS_DIR / e["dir"]
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        publish_at = None
        if settings.PUBLISH_GAP_HOURS > 0:
            when = datetime.now(timezone.utc) + timedelta(hours=settings.PUBLISH_GAP_HOURS * (done + 1))
            publish_at = when.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            yt_id = youtube.upload(folder / "video.mp4", meta, publish_at)
        except youtube.QuotaExceeded:
            log.warning("YouTube quota used up for today; the rest waits for tomorrow")
            state.count_upload(exhausted=True)
            break
        except Exception as e2:  # noqa: BLE001
            log.error("upload failed for %s: %s", e["title"], e2)
            state.update_history(e["id"], status="upload_failed", error=str(e2)[:300])
            continue
        state.count_upload()
        if (folder / "thumbnail.jpg").exists():
            youtube.set_thumbnail(yt_id, folder / "thumbnail.jpg")
        state.update_history(e["id"], status="uploaded", youtube_id=yt_id, uploaded_at=now_iso())
        done += 1
    return done


def cleanup():
    """Delete the video file of uploads older than KEEP_UPLOADED_DAYS (meta + script are kept)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.KEEP_UPLOADED_DAYS)
    for e in state.history():
        if e["status"] == "uploaded" and e.get("uploaded_at") and datetime.fromisoformat(e["uploaded_at"]) < cutoff:
            f = settings.VIDEOS_DIR / e["dir"] / "video.mp4"
            if f.exists():
                f.unlink()
