"""python -m pipeline [--channel NAME] <command>

  add     --category crime --lang hi --format long --count 100 [--minutes 8] [--voice female]
          [--tts clone] [--style 3d] [--edit energetic] [--no-music]
  record  FILE --category drama --lang hi --format long [--style cinematic]
          (your own voiceover file -> video; FILE can be a path or a name inside data/inbox/)
  record  FILE --song --category bhajan --format long [--lyrics FILE.lrc] [--title "Shiv bhajan"]
          (your own song / bhajan / instrumental -> music video with lyrics on screen)
  list                      jobs, how many made / uploaded
  cancel  <job_id>
  make    (same options as add, makes ONE video now, no queue)  [--upload]
  upload                    upload finished videos now (within today's quota)
  review                    videos held back by the quality gate, and why
  approve <video_id> | reject <video_id>
  progress                  subscribers / watch hours / Shorts views vs monetization
  worker                    run forever: make queued videos, upload, sleep (all channels, in turn)
  channels                  list channels;   channel-add NAME   make a new one
  categories | styles | edits | voices
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# --channel must be known before settings is imported: it decides the data folder and .env overrides.
if "--channel" in sys.argv[1:-1]:
    _i = sys.argv.index("--channel")
    os.environ["CHANNEL"] = sys.argv[_i + 1]
    del sys.argv[_i:_i + 2]

from . import insights, llm, maker, settings, state, tts  # noqa: E402
from .util import log, setup_logging  # noqa: E402

IDLE, DAILY_LIMIT = 3, 4  # tick exit codes


def _job_args(p, count=True):
    p.add_argument("--category", required=True)
    p.add_argument("--lang", choices=["hi", "en"], default="hi")
    p.add_argument("--format", choices=["long", "short"], default="short")
    if count:
        p.add_argument("--count", type=int, default=1)
    p.add_argument("--minutes", type=float, default=8, help="long videos only")
    p.add_argument("--voice", choices=["male", "female"], default="male")
    p.add_argument("--tts", choices=["edge", "clone"], default=None,
                   help="clone = your voice sample in data/voices/<voice>.wav")
    p.add_argument("--style", default=None, help="AI image look, see: styles")
    p.add_argument("--no-music", dest="music", action="store_false")
    p.add_argument("--edit", default=None, help="editing style, see: edits")


def _options(a):
    return {"minutes": a.minutes, "voice": a.voice, "tts": a.tts, "style": a.style, "music": a.music, "edit": a.edit}


def cmd_add(a):
    job = state.add_job(a.category, a.lang, a.format, a.count, **_options(a))
    print("added job", job["id"])


def cmd_record(a):
    src = Path(a.file)
    if not src.exists():
        src = settings.INBOX_DIR / a.file
    if not src.exists():
        sys.exit(f"file not found: {a.file} (put it in data/inbox/)")
    if src.parent.resolve() != settings.INBOX_DIR.resolve():
        shutil.copy2(src, settings.INBOX_DIR / src.name)
    extra = {}
    if a.song:
        extra = {"song": True, "title_hint": a.title or ""}
        if a.lyrics:
            lyr = Path(a.lyrics) if Path(a.lyrics).exists() else settings.INBOX_DIR / a.lyrics
            if not lyr.exists():
                sys.exit(f"lyrics file not found: {a.lyrics}")
            if lyr.parent.resolve() != settings.INBOX_DIR.resolve():
                shutil.copy2(lyr, settings.INBOX_DIR / lyr.name)
            extra["lyrics"] = lyr.name
    job = state.add_job(a.category, a.lang, a.format, 1, recording=src.name, **_options(a), **extra)
    print("added", "song" if a.song else "recording", "job", job["id"])


def cmd_list(_):
    hist = state.history()
    for j in state.jobs():
        up = sum(1 for e in hist if e["job"] == j["id"] and e["status"] == "uploaded")
        what = f"rec:{j['recording']}" if j.get("recording") else j["category"]
        print(f"{j['id']}  {j['status']:<9} {what:<14} {j['language']} {j['format']:<5} "
              f"made {j['made']}/{j['count']}  uploaded {up}  failed {j['failed']}")
    ready = sum(1 for e in hist if e["status"] == "ready")
    review = sum(1 for e in hist if e["status"] == "review")
    print(f"\nwaiting to upload: {ready}   held for review: {review}   uploads left today: {state.uploads_left()}   "
          f"Gemini calls today: {llm.calls_today()}")


def cmd_cancel(a):
    state.update_job(a.job_id, status="cancelled")
    print("cancelled", a.job_id)


def cmd_make(a):
    job = {"id": "manual", "category": a.category, "language": a.lang, "format": a.format, **_options(a)}
    for _ in range(a.count):
        maker.make_video(job)
    if a.upload:
        maker.upload_ready()


def cmd_voices(_):
    files = sorted(p.name for p in settings.VOICES_DIR.glob("*") if p.is_file())
    print("samples in data/voices/:", ", ".join(files) or "(none - add male.wav / female.wav)")
    engine = tts.pick_engine("clone", "male")
    print("voice service:", "ready" if engine == "clone" else "not running or no male sample")


def cmd_review(_):
    held = [e for e in state.history() if e["status"] == "review"]
    for e in held:
        meta = json.loads((settings.VIDEOS_DIR / e["dir"] / "meta.json").read_text(encoding="utf-8"))
        print(f"{e['id']}  quality {e.get('quality')}  {e['title']}")
        print(f"          {'; '.join(meta.get('quality_notes') or []) or '-'}"
              + (f"  (looks like: {meta['similar_to']})" if meta.get("similar_to") else ""))
        print(f"          data/videos/{e['dir']}/video.mp4")
    print(f"\n{len(held)} waiting. ./yt approve <id> uploads it, ./yt reject <id> drops it.")


def cmd_set_status(status):
    def go(a):
        state.update_history(a.video_id, status=status)
        print(a.video_id, "->", status)
    return go


def tick(max_uploads=None):
    """One step for the current channel: upload what is due, then make one queued video."""
    try:
        maker.upload_ready(max_uploads)
        maker.cleanup()
        insights.refresh_stats()
    except Exception:  # noqa: BLE001
        log.error("upload/stats error:\n%s", traceback.format_exc())
    job = state.next_job()
    if not job:
        return IDLE
    try:
        maker.make_video(job)
        state.update_job(job["id"], made=1)
    except llm.DailyLimit as e:
        # Not the video's fault: wait for Google's reset, never hammer the free key.
        log.warning("%s - pausing", e)
        return DAILY_LIMIT
    except Exception:  # noqa: BLE001 - one bad video must not stop the queue
        log.error("video failed:\n%s", traceback.format_exc())
        state.update_job(job["id"], failed=1)
        time.sleep(60)
    return 0


def worker(_):
    chans = [] if settings.CHANNEL else settings.channels()
    log.info("worker started (data: %s, channels: %s)", settings.DATA_DIR, ", ".join(chans) or "single")
    while True:
        if not chans:
            code = tick()
        else:
            # Channels take turns, one video and at most one upload each, so a 100-video job on one
            # channel never starves the others. Each turn runs in its own process with its own settings.
            codes = []
            for ch in chans:
                codes.append(subprocess.run([sys.executable, "-m", "pipeline", "--channel", ch, "tick"]).returncode)
            code = DAILY_LIMIT if DAILY_LIMIT in codes else (IDLE if all(c == IDLE for c in codes) else 0)
            chans = settings.channels()  # pick up channels added while running
        if code == DAILY_LIMIT:
            time.sleep(3600)
        elif code == IDLE:
            time.sleep(settings.WORKER_SLEEP_SECONDS)


def cmd_channel_add(a):
    d = settings.CHANNELS_DIR / a.name
    if d.exists():
        sys.exit(f"channel {a.name} already exists: {d}")
    (d / "voices").mkdir(parents=True)
    (d / "inbox").mkdir()
    profile = settings.load_channel() or {}
    profile["name"] = a.name
    (d / "channel.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "channel.env").write_text(
        "# Settings for this channel only; anything not here comes from the main .env.\n"
        "# YouTube login of THIS channel (scripts/get_refresh_token.py, pick this channel's account):\n"
        "YT_REFRESH_TOKEN=\n"
        "# Same OAuth client as the main .env = same Google project = the daily upload quota is shared.\n"
        "# YT_CLIENT_ID=\n# YT_CLIENT_SECRET=\n"
        "# UPLOAD_PRIVACY=private\n# TTS_PROVIDER=edge\n# CHANNEL_FOOTER=\n", encoding="utf-8")
    print(f"created {d}\n  1. edit {d / 'channel.json'} (niche, host, publish times)\n"
          f"  2. put this channel's YT_REFRESH_TOKEN in {d / 'channel.env'}\n"
          f"  3. voices (optional): {d / 'voices'}/male.wav, female.wav\n"
          f"  4. ./yt --channel {a.name} add --category ... --count ...")


def cmd_channels(_):
    for ch in settings.channels():
        d = settings.CHANNELS_DIR / ch
        q = json.loads((d / "queue.json").read_text()) if (d / "queue.json").exists() else {"jobs": []}
        h = json.loads((d / "history.json").read_text()) if (d / "history.json").exists() else []
        left = sum(j["count"] - j["made"] for j in q["jobs"] if j["status"] == "active")
        up = sum(1 for e in h if e["status"] == "uploaded")
        ready = sum(1 for e in h if e["status"] == "ready")
        print(f"{ch:<16} to make {left:<5} ready {ready:<4} uploaded {up}")
    if not settings.channels():
        print("no channels yet (single-channel mode). ./yt channel-add NAME")


def _print_json_keys(path):
    for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items():
        if not k.startswith("_"):
            print(f"{k:<14} {v['label'] + '  (' + v['visuals'] + ')' if isinstance(v, dict) else v[:80]}")


def main(argv=None):
    setup_logging()
    ap = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    _job_args(p)
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("record")
    p.add_argument("file")
    _job_args(p, count=False)
    p.add_argument("--song", action="store_true", help="a song / bhajan / instrumental, not speech")
    p.add_argument("--lyrics", help=".lrc (timed) or .txt lyrics for --song")
    p.add_argument("--title", help="what the song is, e.g. 'Hanuman bhajan'")
    p.set_defaults(fn=cmd_record)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("cancel")
    p.add_argument("job_id")
    p.set_defaults(fn=cmd_cancel)
    p = sub.add_parser("make")
    _job_args(p)
    p.add_argument("--upload", action="store_true")
    p.set_defaults(fn=cmd_make)
    sub.add_parser("upload").set_defaults(fn=lambda a: print("uploaded", maker.upload_ready()))
    sub.add_parser("worker").set_defaults(fn=worker)
    sub.add_parser("tick").set_defaults(fn=lambda a: sys.exit(tick(max_uploads=1)))
    p = sub.add_parser("channel-add")
    p.add_argument("name")
    p.set_defaults(fn=cmd_channel_add)
    sub.add_parser("channels").set_defaults(fn=cmd_channels)
    sub.add_parser("review").set_defaults(fn=cmd_review)
    for name, status in (("approve", "ready"), ("reject", "rejected")):
        p = sub.add_parser(name)
        p.add_argument("video_id")
        p.set_defaults(fn=cmd_set_status(status))
    sub.add_parser("progress").set_defaults(fn=lambda a: print(insights.progress()))
    sub.add_parser("voices").set_defaults(fn=cmd_voices)
    sub.add_parser("categories").set_defaults(fn=lambda a: _print_json_keys(settings.ROOT / "config/categories.json"))
    sub.add_parser("styles").set_defaults(fn=lambda a: _print_json_keys(settings.ROOT / "config/styles.json"))
    sub.add_parser("edits").set_defaults(fn=lambda a: [
        print(f"{k:<11} {', '.join(v['transitions'][:4])} | {v['captions']} captions | grade {v['grade']}"
              f"{' | whoosh' if v['sfx'] else ''}{' | punch zoom' if v['punch'] else ''}"
              f"{' | progress bar' if v['progress'] else ''}")
        for k, v in json.loads((settings.ROOT / "config/edits.json").read_text()).items() if not k.startswith("_")])
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
