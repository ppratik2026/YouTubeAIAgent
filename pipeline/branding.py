"""Channel branding: logo watermark, a short intro sting and an outro card.

Files (per channel in data/channels/<name>/branding/, or shared in data/branding/):
  logo.png    watermark (transparent PNG works best)
  intro.mp4   your own intro; without it one is made from the channel name and colour
  outro.mp4   your own outro; without it a card is made with room for YouTube's end-screen elements

Settings in channel.json -> "branding". The intro is off by default: a channel intro before the hook is
the classic reason people leave in the first seconds. The outro (long videos) gives YouTube's end screen
its 5-20 seconds to show "next video" and "subscribe".
"""
from pathlib import Path

from . import settings
from .util import run

DEFAULTS = {"color": "#1D3557", "accent": "#FFD700", "watermark": True, "watermark_opacity": 0.75,
            "intro": False, "intro_seconds": 2.0, "outro": True, "outro_seconds": 8.0,
            "outro_text": {"hi": "देखते रहिए - अगला वीडियो यहाँ", "en": "Watch next"}}


def config():
    cfg = dict(DEFAULTS)
    cfg.update(settings.load_channel().get("branding") or {})
    return cfg


def _file(name):
    for folder in (settings.DATA_DIR / "branding", settings.SHARED_DIR / "branding"):
        p = folder / name
        if p.exists():
            return p
    return None


def logo():
    return _file("logo.png") if config()["watermark"] else None


def _ass_colour(hex_rgb):
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _card(work, name, w, h, seconds, lines, font, bg, with_logo=True):
    """A colour card with animated text lines (libass, so Hindi is shaped right) and the logo."""
    ass = Path(work) / f"{name}.ass"
    events = []
    for i, (text, size, colour, y) in enumerate(lines):
        start = 0.15 + i * 0.25
        events.append(
            f"Dialogue: 0,0:00:{start:05.2f},0:00:{seconds:05.2f},C,,0,0,0,,"
            f"{{\\an5\\pos({w // 2},{y})\\fs{size}\\c{colour}\\fad(250,250)\\fscx80\\fscy80"
            f"\\t(0,300,\\fscx100\\fscy100)}}{text}")
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: C,{font},60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,5,0,0,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n", encoding="utf-8")
    out = Path(work) / f"{name}.mp4"
    esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={bg.replace('#', '0x')}:s={w}x{h}:r={settings.FPS}:d={seconds}"]
    lg = _file("logo.png") if with_logo else None
    if lg:
        size = min(w, h) // 4
        cmd += ["-loop", "1", "-i", str(lg), "-filter_complex",
                f"[1:v]scale={size}:-1,format=rgba,fade=t=in:st=0:d=0.4:alpha=1[l];"
                f"[0:v][l]overlay=(W-w)/2:(H/2-h-{h // 14}):shortest=1,subtitles='{esc}',vignette=PI/4[v]",
                "-map", "[v]"]
    else:
        cmd += ["-vf", f"subtitles='{esc}',vignette=PI/4"]
    cmd += ["-t", f"{seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)]
    run(cmd)
    return out


def intro(work, w, h, font):
    cfg = config()
    if not cfg["intro"]:
        return None
    own = _file("intro.mp4")
    if own:
        return own
    name = settings.load_channel().get("name") or "My Channel"
    return _card(work, "intro", w, h, float(cfg["intro_seconds"]), [
        (name, max(60, w // 14), _ass_colour("#FFFFFF"), h // 2 + h // 20)], font, cfg["color"])


def outro(work, w, h, font, language, portrait):
    cfg = config()
    if not cfg["outro"] or portrait:  # Shorts loop; an outro card kills the loop
        return None
    own = _file("outro.mp4")
    if own:
        return own
    name = settings.load_channel().get("name") or ""
    text = cfg["outro_text"].get(language, cfg["outro_text"]["en"]) if isinstance(cfg["outro_text"], dict) \
        else cfg["outro_text"]
    # Text sits high; the lower half stays clear for the end-screen video and subscribe elements.
    return _card(work, "outro", w, h, float(cfg["outro_seconds"]), [
        (text, w // 22, _ass_colour(cfg["accent"]), h // 6),
        (name, w // 30, _ass_colour("#FFFFFF"), h // 6 + w // 18)], font, cfg["color"], with_logo=False)
