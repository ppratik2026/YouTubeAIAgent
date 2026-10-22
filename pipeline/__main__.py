"""python -m pipeline <command>

  add --category crime --lang hi --format long --count 100 [--minutes 8] [--voice female]
  list                      jobs, how many made / uploaded
  cancel <job_id>
  make  (same options as add, makes ONE video now, no queue)  [--upload]
  upload                    upload finished videos now (within today's quota)
  worker                    run forever: make queued videos, upload, sleep
  categories
"""
import argparse
import sys
import time
import traceback

from . import maker, settings, state
from .util import log, setup_logging


def _job_args(p):
    p.add_argument("--category", required=True)
    p.add_argument("--lang", choices=["hi", "en"], default="hi")
    p.add_argument("--format", choices=["long", "short"], default="short")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--minutes", type=float, default=8, help="long videos only")
    p.add_argument("--voice", choices=["male", "female"], default="male")


def cmd_list(_):
    hist = state.history()
    for j in state.jobs():
        up = sum(1 for e in hist if e["job"] == j["id"] and e["status"] == "uploaded")
        print(f"{j['id']}  {j['status']:<8} {j['category']:<12} {j['language']} {j['format']:<5} "
              f"made {j['made']}/{j['count']}  uploaded {up}  failed {j['failed']}")
    ready = sum(1 for e in hist if e["status"] == "ready")
    print(f"\nwaiting to upload: {ready}   uploads left today: {state.uploads_left()}")


def cmd_cancel(a):
    state.update_job(a.job_id, status="cancelled")
    print("cancelled", a.job_id)


def cmd_make(a):
    job = {"id": "manual", "category": a.category, "language": a.lang, "format": a.format,
           "minutes": a.minutes, "voice": a.voice}
    for _ in range(a.count):
        maker.make_video(job)
    if a.upload:
        maker.upload_ready()


def worker(_):
    log.info("worker started (data: %s)", settings.DATA_DIR)
    while True:
        try:
            maker.upload_ready()
            maker.cleanup()
            job = state.next_job()
            if job:
                try:
                    maker.make_video(job)
                    state.update_job(job["id"], made=1)
                except Exception:  # noqa: BLE001 - one bad video must not stop the queue
                    log.error("video failed:\n%s", traceback.format_exc())
                    state.update_job(job["id"], failed=1)
                    time.sleep(60)
                continue
        except Exception:  # noqa: BLE001
            log.error("worker error:\n%s", traceback.format_exc())
        time.sleep(settings.WORKER_SLEEP_SECONDS)


def main(argv=None):
    setup_logging()
    ap = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    _job_args(p)
    p.set_defaults(fn=lambda a: print("added job", state.add_job(
        a.category, a.lang, a.format, a.count, a.minutes, a.voice)["id"]))
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
    sub.add_parser("categories").set_defaults(fn=lambda a: [
        print(f"{k:<14} {v['label']}  ({v['visuals']})") for k, v in settings.load_categories().items()
        if not k.startswith("_")])
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
