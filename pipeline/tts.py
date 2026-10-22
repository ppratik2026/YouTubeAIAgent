"""Narration. edge-tts gives free Microsoft neural voices in Hindi and English with no key.
"offline" makes silent audio of the right length so rendering can be tested without the network."""
import asyncio

from . import settings
from .util import log, retry, run

VOICES = {
    ("hi", "male"): "hi-IN-MadhurNeural",
    ("hi", "female"): "hi-IN-SwaraNeural",
    ("en", "male"): "en-IN-PrabhatNeural",
    ("en", "female"): "en-IN-NeerjaNeural",
}
# mood -> (rate, pitch)
MOODS = {
    "neutral": ("+5%", "+0Hz"), "tense": ("-5%", "-4Hz"), "emotional": ("-3%", "-2Hz"),
    "uplifting": ("+8%", "+2Hz"), "playful": ("+6%", "+4Hz"),
}


def voice_for(language, gender):
    return settings.env(f"VOICE_{language.upper()}_{gender.upper()}") or VOICES.get(
        (language, gender), VOICES[("en", "male")])


def _edge(text, voice, rate, pitch, out):
    import edge_tts  # imported here so offline tests do not need it

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))
    asyncio.run(go())


def speak(text, out_mp3, language, gender="male", mood="neutral"):
    rate, pitch = MOODS.get(mood, MOODS["neutral"])
    if settings.TTS_PROVIDER == "offline":
        secs = max(1.5, len(text.split()) / 2.6)
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
             "-t", f"{secs:.2f}", "-af", "volume=0.05", str(out_mp3)])
        return out_mp3
    voice = voice_for(language, gender)
    retry(lambda: _edge(text, voice, rate, pitch, out_mp3), tries=4, wait=5, what="edge-tts")
    log.debug("tts %s %s", voice, out_mp3)
    return out_mp3
