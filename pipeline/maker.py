"""One job step = one finished video folder: video.mp4, thumbnail.jpg, meta.json, script.txt.

What keeps the channel looking like one real creator (and monetizable) rather than a content farm:
the channel profile in every script, a different video shape and hook formula each time, a check
against earlier scripts, a quality gate before upload, Shorts that send viewers to the long videos,
uploads on fixed prime-time slots, and topic choice that learns from this channel's own numbers."""
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import insights, quality, render, settings, state, thumbs, transcribe, tts, visuals, writer, youtube
from .util import duration, log, now_iso, read_json, run, slug, write_json

SCHEDULE = settings.DATA_DIR / "schedule.json"


def category(name, style=None):
    cats = settings.load_categories()
    if name in cats:
        cat = dict(cats[name], key=name)
    else:
        # Any category the user types works: an original-content explainer with stock footage.
        cat = {"key": name, "label": name, "visuals": "stock", "news": False, "mood": "neutral",
               "youtube_category": "22", "tone": f"An original, engaging video in the '{name}' category."}
    if style:  # --style turns any category into AI images in that look
        cat.update(style=style, visuals="ai")
    return cat


def _new_work():
    vid_id = uuid.uuid4().hex[:8]
    work = settings.WORK_DIR / vid_id
    work.mkdir(parents=True, exist_ok=True)
    return vid_id, work


def _pictures(scenes, cat, portrait, work):
    used, seed = set(), visuals.new_seed()
    for n, sc in enumerate(scenes):
        sc["visual"], sc["kind"] = visuals.for_scene(sc, cat, portrait, used, work / f"img{n:03d}", n, seed,
                                                     rewrite=writer.safe_image_prompt)


def _script_text(script):
    return "\n\n".join(f"## {sec['heading']}\n" + "\n".join(s["narration"] for s in sec["scenes"])
                       for sec in script["sections"])


def _recent(category, key, n=6):
    return [e[key] for e in state.history() if e["category"] == category and e.get(key)][-n:]


def _finish(job, cat, vid_id, work, script, meta, topic, gap, hook=None, extra=None):
    """Render, thumbnail, description, quality gate, files, history entry."""
    lang, fmt = job["language"], job["format"]
    portrait = fmt == "short"
    scenes, starts = [], []
    for sec in script["sections"]:
        starts.append((sec["heading"], len(scenes)))
        scenes += sec["scenes"]
    if len(scenes) < 3:
        raise RuntimeError(f"script too short ({len(scenes)} scenes)")

    text = _script_text(script)
    similar, similar_to = quality.most_similar(text, job["category"])
    out = settings.VIDEOS_DIR / f"{datetime.now():%Y%m%d-%H%M}-{slug(meta['title'])}-{vid_id}"
    out.mkdir(parents=True)
    style = job.get("edit") or cat.get("edit") or ("energetic" if portrait else "cinematic")
    if job.get("song"):
        style = job.get("edit") or ("karaoke" if job.get("lyrics") else "calm")
    total = render.render(scenes, lang, portrait, cat["mood"], work, out / "video.mp4", gap=gap,
                          music=job.get("music", True), style=style)

    desc = [meta["description"]]
    if not portrait:
        ch = render.chapters([(h, scenes[i]["start"]) for h, i in starts], total)
        if ch:
            desc.append(ch)
        thumbs.make(meta, scenes, cat, lang, work, out)
    if topic.get("facts"):
        desc.append("Sources: " + ", ".join(sorted({f["source"] for f in topic["facts"] if f["source"]})))
    if any(s["kind"] == "video" for s in scenes) or cat.get("visuals") == "stock":
        desc.append("Stock footage: Pexels")
    if settings.CHANNEL_FOOTER:
        desc.append(settings.CHANNEL_FOOTER)

    score, reasons = quality.score(meta, scenes, hook, similar)
    q_min = settings.load_channel().get("quality_min", 55)
    status = "ready" if score >= q_min and similar < quality.MAX_SIMILARITY else "review"
    if status == "review":
        log.warning("quality %s < %s or too similar (%s) - held for ./yt review: %s",
                    score, q_min, similar_to or "-", "; ".join(reasons))

    meta.update(description="\n\n".join(d for d in desc if d).strip(), language=lang,
                category_id=cat["youtube_category"], duration=round(total, 1), topic=topic["topic"],
                hook=hook["text"] if hook else "", hook_score=hook["score"]["verdict"] if hook else None,
                quality=score, quality_notes=reasons, similar_to=similar_to, similarity=round(similar, 3),
                # What was said when - lets retention drops be traced back to the exact line.
                timeline=[{"start": round(s["start"], 2), "end": round(s["start"] + s["dur"], 2),
                           "text": s["narration"]} for s in scenes])
    (out / "script.txt").write_text(text, encoding="utf-8")
    write_json(out / "meta.json", meta)
    shutil.rmtree(work, ignore_errors=True)

    entry = {"id": vid_id, "job": job["id"], "category": job["category"], "language": lang, "format": fmt,
             "topic": topic["topic"], "source_title": topic.get("source_title", ""), "title": meta["title"],
             # dir is relative, so data/ can move to another server
             "dir": out.name, "made_at": now_iso(), "status": status, "duration": meta["duration"],
             "quality": score, "edit": style, **(extra or {})}
    state.add_history(entry)
    log.info("made %s (%.0fs, quality %s) -> %s", meta["title"], total, score, out)
    return entry


def make_video(job):
    if job.get("recording"):
        return make_from_recording(job)
    cat = category(job["category"], job.get("style"))
    lang, fmt = job["language"], job["format"]
    portrait = fmt == "short"
    vid_id, work = _new_work()
    log.info("== %s %s %s video (job %s) ==", cat["label"], lang, fmt, job["id"])

    parent = None
    if job.get("from_video"):  # a Short cut from one of our long videos
        p = next((e for e in state.history() if e["id"] == job["from_video"]), None)
        if p and (settings.VIDEOS_DIR / p["dir"] / "script.txt").exists():
            parent = (settings.VIDEOS_DIR / p["dir"] / "script.txt").read_text(encoding="utf-8")
            topic = {"topic": p["topic"], "angle": "one moment from the full video", "facts": []}
    if not parent:
        insights.refresh_stats()
        topic = writer.pick_topic(cat, lang, fmt, state.used_titles(job["category"]),
                                  insights.performance_block(job["category"], fmt))
    log.info("topic: %s", topic["topic"])

    structure = writer.pick_structure(_recent(job["category"], "structure"))
    hook = writer.best_hook(cat, lang, fmt, topic, _recent(job["category"], "formula"))[0]
    lessons = insights.lessons_block(job["category"], fmt)
    script = (writer.write_short(cat, lang, topic, hook, structure, parent, lessons) if portrait
              else writer.write_long(cat, lang, topic, hook, job.get("minutes") or 8, structure, lessons))
    meta = writer.package(cat, lang, fmt, topic, script)

    gender = job.get("voice") or "male"
    engine = tts.pick_engine(job.get("tts"), gender)
    log.info("voice: %s %s | shape: %s", engine, gender, structure.split(":")[0])
    scenes = [sc for sec in script["sections"] for sc in sec["scenes"]]
    for n, sc in enumerate(scenes):
        sc["audio"] = tts.speak(sc["narration"], work / f"s{n:03d}", lang, gender, cat["mood"], engine)
    _pictures(scenes, cat, portrait, work)
    entry = _finish(job, cat, vid_id, work, script, meta, topic, render.GAP, hook, extra={
        "formula": hook["score"]["formula"], "structure": structure, "parent": job.get("from_video")})

    shorts = int(settings.load_channel().get("shorts_per_long", 0))
    if fmt == "long" and shorts > 0 and job["id"] != "manual":
        # Shorts pull new viewers to the long video, which is where watch hours come from.
        state.add_job(job["category"], lang, "short", shorts, from_video=vid_id, voice=job.get("voice"),
                      tts=job.get("tts"), style=job.get("style"), music=job.get("music", True))  # Shorts get their own edit style
        log.info("queued %d Shorts from this video", shorts)
    return entry


def make_from_recording(job):
    """Your own audio file -> video. The audio is used exactly as given; nothing is re-voiced.

    speech (default): whisper transcribes it -> scenes, subtitles, pictures
    song (--song):    a bhajan / song / instrumental you own or may use. Lyrics come from your .lrc
                      (timed) or .txt file, or none for instrumental; no background music is added."""
    rec = settings.INBOX_DIR / job["recording"]
    if not rec.exists():
        raise RuntimeError(f"recording not found: {rec}")
    cat = category(job["category"], job.get("style"))
    lang, fmt = job["language"], job["format"]
    vid_id, work = _new_work()
    song = bool(job.get("song"))
    log.info("== %s %s -> %s %s %s video ==", "song" if song else "recording", rec.name, cat["label"], lang, fmt)

    if song:
        total = duration(rec)
        lyrics = settings.INBOX_DIR / job["lyrics"] if job.get("lyrics") else None
        scenes = (transcribe.scenes_from_lyrics(lyrics, total) if lyrics and lyrics.exists()
                  else transcribe.instrumental_scenes(total))
        job = dict(job, music=False)  # never lay music over a song
    else:
        scenes = transcribe.scenes_from_recording(rec, lang)
    for n, sc in enumerate(scenes):
        sc["audio"] = work / f"s{n:03d}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{sc['start']:.3f}", "-to", f"{sc['end']:.3f}",
             "-i", str(rec), "-ar", "44100", "-ac", "2", str(sc["audio"])])
    about = job.get("title_hint") or ""
    script = writer.visuals_for_transcript(cat, lang, scenes, about)
    words = " ".join(s["narration"] for s in scenes).strip()
    topic = {"topic": (about or words or rec.stem)[:120], "facts": []}
    meta = writer.package(cat, lang, fmt, topic, script, about)
    _pictures(scenes, cat, fmt == "short", work)
    entry = _finish(job, cat, vid_id, work, script, meta, topic, gap=0.0,
                    extra={"own_voice": not song, "song": song})
    done = settings.INBOX_DIR / "done"
    done.mkdir(exist_ok=True)
    for f in (rec, settings.INBOX_DIR / job["lyrics"] if job.get("lyrics") else None):
        if f and f.exists():
            shutil.move(str(f), str(done / f.name))
    return entry


# ---------- upload ----------

def _next_slot():
    """Next free prime-time slot (channel.json publish_times_ist), one video per slot, never sooner
    than an hour from now. Same times every day is what lets an audience form a habit."""
    times = settings.load_channel().get("publish_times_ist") or []
    if not times:
        return None
    ist = ZoneInfo("Asia/Kolkata")
    last = read_json(SCHEDULE, {}).get("last")
    after = max(datetime.now(ist) + timedelta(hours=1),
                datetime.fromisoformat(last).astimezone(ist) if last else datetime.min.replace(tzinfo=ist))
    day = after.date()
    for _ in range(60):
        for t in sorted(times):
            h, m = map(int, t.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=ist)
            if slot > after:
                write_json(SCHEDULE, {"last": slot.isoformat()})
                return slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        day += timedelta(days=1)
    return None


def _publish_at(done):
    if settings.UPLOAD_PRIVACY != "public":
        return None  # private/unlisted: you publish by hand in Studio
    if settings.PUBLISH_GAP_HOURS > 0:
        when = datetime.now(timezone.utc) + timedelta(hours=settings.PUBLISH_GAP_HOURS * (done + 1))
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _next_slot()


def upload_ready(max_uploads=None):
    """Upload finished videos, oldest first, as far as today's quota allows (and at most max_uploads,
    so channels sharing a quota take turns)."""
    if not (settings.AUTO_UPLOAD and youtube.configured()):
        return 0
    done = 0
    hist = state.history()
    by_id = {e["id"]: e for e in hist}
    for e in [e for e in hist if e["status"] == "ready"]:
        if state.uploads_left() <= 0 or (max_uploads is not None and done >= max_uploads):
            break
        parent = by_id.get(e.get("parent") or "")
        if parent and parent["status"] in ("ready", "review"):
            continue  # upload the long video first so the Short can link to it
        folder = settings.VIDEOS_DIR / e["dir"]
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        if parent and parent.get("youtube_id"):
            meta["description"] = f"Full video: https://youtu.be/{parent['youtube_id']}\n\n{meta['description']}"
        publish_at = _publish_at(done)
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
        state.update_history(e["id"], status="uploaded", youtube_id=yt_id, uploaded_at=now_iso(),
                             publish_at=publish_at)
        e.update(status="uploaded", youtube_id=yt_id)  # its Shorts later in this loop can now go
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
