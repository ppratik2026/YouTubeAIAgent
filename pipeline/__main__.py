"""python -m pipeline <command>

  add     --category crime --lang hi --format long --count 100 [--minutes 8] [--voice female]
          [--tts clone] [--style 3d] [--no-music]
  record  FILE --category drama --lang hi --format long [--style cinematic]
          (your own voiceover file -> video; FILE can be a path or a name inside data/inbox/)
  list                      jobs, how many made / uploaded
  cancel  <job_id>
  make    (same options as add, makes ONE video now, no queue)  [--upload]
  upload                    upload finished videos now (within today's quota)
  review                    videos held back by the quality gate, and why
  approve <video_id> | reject <video_id>
  progress                  subscribers / watch hours / Shorts views vs monetization
  worker                    run forever: make queued videos, upload, sleep
  categories | styles | voices
"""
import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

from . import insights, llm, maker, settings, state, tts
from .util import log, setup_logging


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


def _options(a):
    return {"minutes": a.minutes, "voice": a.voice, "tts": a.tts, "style": a.style, "music": a.music}


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
    job = state.add_job(a.category, a.lang, a.format, 1, recording=src.name, **_options(a))
    print("added recording job", job["id"])


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


def worker(_):
    log.info("worker started (data: %s)", settings.DATA_DIR)
    while True:
        try:
            maker.upload_ready()
            maker.cleanup()
            insights.refresh_stats()
            job = state.next_job()
            if job:
                try:
                    maker.make_video(job)
                    state.update_job(job["id"], made=1)
                except llm.DailyLimit as e:
                    # Not the video's fault: wait for Google's reset, never hammer the free key.
                    log.warning("%s - pausing 1 hour", e)
                    time.sleep(3600)
                except Exception:  # noqa: BLE001 - one bad video must not stop the queue
                    log.error("video failed:\n%s", traceback.format_exc())
                    state.update_job(job["id"], failed=1)
                    time.sleep(60)
                continue
        except Exception:  # noqa: BLE001
            log.error("worker error:\n%s", traceback.format_exc())
        time.sleep(settings.WORKER_SLEEP_SECONDS)


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
    sub.add_parser("review").set_defaults(fn=cmd_review)
    for name, status in (("approve", "ready"), ("reject", "rejected")):
        p = sub.add_parser(name)
        p.add_argument("video_id")
        p.set_defaults(fn=cmd_set_status(status))
    sub.add_parser("progress").set_defaults(fn=lambda a: print(insights.progress()))
    sub.add_parser("voices").set_defaults(fn=cmd_voices)
    sub.add_parser("categories").set_defaults(fn=lambda a: _print_json_keys(settings.ROOT / "config/categories.json"))
    sub.add_parser("styles").set_defaults(fn=lambda a: _print_json_keys(settings.ROOT / "config/styles.json"))
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
