"""Your own recording -> timed scenes, with faster-whisper on the CPU (free, offline after the
first model download)."""
import re

from . import settings
from .util import log


def scenes_from_recording(path, language, target=9.0, longest=14.0):
    """Whisper segments grouped into scenes of ~target seconds, cut only where a sentence ends.
    Each scene: {narration, start, end} in seconds of the original recording."""
    from faster_whisper import WhisperModel  # imported here: only this feature needs it

    log.info("transcribing %s with whisper '%s' (first time downloads the model)", path, settings.WHISPER_MODEL)
    model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8",
                         download_root=str(settings.DATA_DIR / "models"))
    segments, info = model.transcribe(str(path), language=language, vad_filter=True)
    segs = [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
    if not segs:
        raise RuntimeError("no speech found in the recording")

    scenes, cur = [], None
    for start, end, text in segs:
        if cur is None:
            cur = {"start": start, "end": end, "narration": text}
            continue
        sentence_done = cur["narration"].rstrip().endswith((".", "?", "!", "।", "|"))
        if (cur["end"] - cur["start"] >= target and sentence_done) or end - cur["start"] > longest:
            scenes.append(cur)
            cur = {"start": start, "end": end, "narration": text}
        else:
            cur["end"], cur["narration"] = end, f"{cur['narration']} {text}"
    scenes.append(cur)
    # Scenes touch each other so no word of the recording is lost between them.
    scenes[0]["start"] = 0.0
    for a, b in zip(scenes, scenes[1:]):
        a["end"] = b["start"]
    scenes[-1]["end"] = info.duration
    log.info("%d scenes from %.0fs of audio", len(scenes), info.duration)
    return scenes


def _ts(s):
    m, sec = s.split(":", 1)
    return int(m) * 60 + float(sec)


def scenes_from_lyrics(lyrics_path, total, target=8.0):
    """Lyrics you provide for a song (whisper is unreliable on singing).
    .lrc  -> each timed line is a scene ([mm:ss.xx] text)
    .txt  -> one line per lyric line, spread evenly over the song (rough; prefer .lrc)"""
    text = lyrics_path.read_text(encoding="utf-8")
    timed = []
    for line in text.splitlines():
        for m in re.finditer(r"\[(\d+:\d+(?:\.\d+)?)\]", line):
            timed.append((_ts(m.group(1)), re.sub(r"\[[^\]]*\]", "", line).strip()))
    if timed:
        timed.sort()
        scenes = [{"start": t, "narration": words} for t, words in timed]
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return instrumental_scenes(total, target)
        step = total / len(lines)
        scenes = [{"start": i * step, "narration": ln} for i, ln in enumerate(lines)]
    scenes[0]["start"] = 0.0
    for a, b in zip(scenes, scenes[1:]):
        a["end"] = b["start"]
    scenes[-1]["end"] = total
    return [s for s in scenes if s["end"] - s["start"] > 0.5]


def instrumental_scenes(total, target=10.0):
    """No words: just a new picture every ~target seconds."""
    n = max(1, round(total / target))
    step = total / n
    return [{"start": i * step, "end": (i + 1) * step, "narration": ""} for i in range(n)]
