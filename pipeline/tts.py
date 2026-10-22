"""Narration, free:
  edge    - Microsoft neural voices through edge-tts (Hindi + English, no key)
  clone   - your own voice samples (data/voices/male.wav, female.wav) through the voice service
  offline - quiet tone of the right length, for tests without the network

The engine is chosen once per video, so a video never switches voice halfway."""
import asyncio

from . import settings
from .util import HTTP, log, retry, run

VOICES = {
    ("hi", "male"): "hi-IN-MadhurNeural",
    ("hi", "female"): "hi-IN-SwaraNeural",
    ("en", "male"): "en-IN-PrabhatNeural",
    ("en", "female"): "en-IN-NeerjaNeural",
}
# mood -> (edge rate, edge pitch, clone exaggeration)
MOODS = {
    "neutral": ("+5%", "+0Hz", 0.45), "tense": ("-5%", "-4Hz", 0.55), "emotional": ("-3%", "-2Hz", 0.65),
    "uplifting": ("+8%", "+2Hz", 0.6), "playful": ("+6%", "+4Hz", 0.7),
}


def voice_for(language, gender):
    return settings.env(f"VOICE_{language.upper()}_{gender.upper()}") or VOICES.get(
        (language, gender), VOICES[("en", "male")])


def pick_engine(requested, gender):
    """'clone' only if the voice service answers and has a sample for this voice; else 'edge'."""
    engine = requested or settings.TTS_PROVIDER
    if engine != "clone":
        return engine
    fallback = settings.TTS_PROVIDER if settings.TTS_PROVIDER != "clone" else "edge"
    try:
        r = HTTP.get(f"{settings.VOICE_SERVER}/health", timeout=10)
        voices = r.json().get("voices", []) if r.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        log.warning("voice service not reachable (%s) - using the %s voice for this video", e, fallback)
        return fallback
    if gender not in voices:
        log.warning("no voice sample data/voices/%s.wav - using the %s voice for this video", gender, fallback)
        return fallback
    return "clone"


def _edge(text, voice, rate, pitch, out):
    import edge_tts  # imported here so offline tests do not need it

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))
    asyncio.run(go())


def _clone(text, language, gender, exaggeration, out):
    # CPU generation is slow: a long sentence can take a minute or more.
    r = HTTP.post(f"{settings.VOICE_SERVER}/tts", timeout=900, json={
        "text": text, "language": language, "voice": gender, "exaggeration": exaggeration})
    if r.status_code != 200:
        raise RuntimeError(f"voice service {r.status_code}: {r.text[:300]}")
    out.write_bytes(r.content)


def speak(text, out_base, language, gender="male", mood="neutral", engine="edge"):
    """Writes out_base with the right extension and returns that path."""
    rate, pitch, exaggeration = MOODS.get(mood, MOODS["neutral"])
    if engine == "offline":
        out = out_base.with_suffix(".mp3")
        secs = max(1.5, len(text.split()) / 2.6)
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
             "-t", f"{secs:.2f}", "-af", "volume=0.05", str(out)])
        return out
    if engine == "clone":
        out = out_base.with_suffix(".wav")
        retry(lambda: _clone(text, language, gender, exaggeration, out), tries=3, wait=10, what="voice clone")
        return out
    out = out_base.with_suffix(".mp3")
    retry(lambda: _edge(text, voice_for(language, gender), rate, pitch, out), tries=4, wait=5, what="edge-tts")
    return out
