"""Your own recording -> timed scenes, with faster-whisper on the CPU (free, offline after the
first model download)."""
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
