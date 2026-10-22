"""Second-language versions: one video, made again in another language for another channel, reusing
its pictures and footage (no new image generation, no Pexels calls). Only the words, the voice, the
title and the description are new.

The source video keeps an assets/ folder until every requested version is made; then it is deleted."""
import json
import shutil
from pathlib import Path

from . import settings, state
from .llm import ask_json
from .util import log, now_iso, read_json, write_json


def save_assets(out_dir, script, cat_key, job):
    """Copy what a re-render needs next to the video: pictures + the scene list."""
    assets = Path(out_dir) / "assets"
    assets.mkdir(exist_ok=True)
    sections = []
    for sec in script["sections"]:
        rows = []
        for sc in sec["scenes"]:
            src = Path(sc["visual"])
            dest = assets / f"{len(list(assets.iterdir())):03d}{src.suffix}"
            shutil.copy2(src, dest)
            rows.append({"narration": sc["narration"], "emphasis": sc.get("emphasis") or [],
                         "visual": dest.name, "kind": sc["kind"]})
        sections.append({"heading": sec["heading"], "scenes": rows})
    write_json(assets / "scenes.json", {"category": cat_key, "style": job.get("style"), "edit": job.get("edit"),
                                        "voice": job.get("voice"), "sections": sections})


def queue_versions(out_dir, job, vid_id):
    """Put a translation job into each target channel's queue."""
    for target in job.get("also") or []:
        lang, _, channel = target.partition(":")
        folder = settings.CHANNELS_DIR / channel if channel else settings.DATA_DIR
        if channel and not (folder / "channel.json").exists():
            log.warning("--also %s: no channel '%s', skipped", target, channel)
            continue
        new = {"id": f"tr{vid_id}{lang}", "category": job["category"], "language": lang, "format": job["format"],
               "count": 1, "translate_from": str(Path(out_dir).resolve()), "voice": job.get("voice"),
               "tts": job.get("tts"), "edit": job.get("edit"), "music": job.get("music", True),
               "made": 0, "failed": 0, "status": "active", "created": now_iso()}
        with state.locked():
            q = read_json(folder / "queue.json", {"jobs": []})
            q["jobs"].append(new)
            write_json(folder / "queue.json", q)
        log.info("queued a %s version for %s", lang, channel or "this channel")


def load(src_dir, language):
    """The source scenes, translated. Pictures point at the source's assets folder."""
    assets = Path(src_dir) / "assets"
    data = json.loads((assets / "scenes.json").read_text(encoding="utf-8"))
    lines = [sc["narration"] for sec in data["sections"] for sc in sec["scenes"]]
    heads = [sec["heading"] for sec in data["sections"]]
    name = {"hi": "Hindi (natural spoken Hindi in Devanagari)", "en": "simple English for an Indian audience"}
    out = ask_json(
        f"Translate this video script into {name.get(language, language)}. It is SPOKEN: keep it natural "
        "and as short as the original, not word for word. Keep every line separate and in order; numbers, "
        "names and facts unchanged.\n"
        f"Chapter titles: {json.dumps(heads, ensure_ascii=False)}\nLines: {json.dumps(lines, ensure_ascii=False)}\n"
        f'JSON: {{"headings": [{len(heads)} items], "lines": [{len(lines)} items], '
        '"emphasis": [one list of 1-2 key words per line]}',
        "You translate video scripts. Reply with JSON only.", temperature=0.3,
        offline=lambda: {"headings": heads, "lines": lines, "emphasis": [[] for _ in lines]})
    new_lines = out.get("lines") or []
    if len(new_lines) != len(lines):
        raise RuntimeError(f"translation returned {len(new_lines)} lines for {len(lines)}")
    new_heads = out.get("headings") or heads
    emph = out.get("emphasis") or [[] for _ in lines]
    k = 0
    for i, sec in enumerate(data["sections"]):
        sec["heading"] = new_heads[i] if i < len(new_heads) else sec["heading"]
        for sc in sec["scenes"]:
            sc["narration"] = new_lines[k]
            sc["emphasis"] = emph[k] if k < len(emph) else []
            sc["visual"] = assets / sc["visual"]
            k += 1
    return data


def done_with(src_dir, finished_job_id):
    """Delete the source's assets once no other queued translation still needs them."""
    src = str(Path(src_dir).resolve())
    for qf in [settings.SHARED_DIR / "queue.json", *settings.CHANNELS_DIR.glob("*/queue.json")]:
        for j in read_json(qf, {"jobs": []})["jobs"]:
            if (j.get("translate_from") == src and j["id"] != finished_job_id
                    and j["status"] == "active" and j["made"] < j["count"]):
                return
    shutil.rmtree(Path(src_dir) / "assets", ignore_errors=True)
