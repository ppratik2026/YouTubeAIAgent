"""Thumbnails: three versions, the strongest one picked, all three kept.

Backgrounds: an AI image made for the thumbnail (close-up, emotion, space for text) plus the most
colourful, contrasty frames of the video. Layouts: big text left, a band at the bottom, huge centred
words. The pick is a heuristic (colour + contrast of the picture); real CTR only comes from YouTube
Studio's "Test & compare", which the API cannot drive - so thumb_1..3.jpg stay in the video folder for
you to upload there."""
import re
import shutil
from pathlib import Path

from . import settings, visuals
from .util import log, run

W, H = 1280, 720
LAYOUTS = ["left", "band", "center"]


def _esc(p):
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _score(img):
    """Colourfulness + contrast from ffmpeg's signalstats, 0-100-ish."""
    p = run(["ffmpeg", "-v", "error", "-i", str(img), "-vf",
             "scale=320:-1,signalstats,metadata=print:file=-", "-frames:v", "1", "-f", "null", "-"])
    vals = dict(re.findall(r"lavfi\.signalstats\.(\w+)=([\d.]+)", p))
    sat = float(vals.get("SATAVG", 0))
    contrast = float(vals.get("YHIGH", 0)) - float(vals.get("YLOW", 0))
    return round(sat * 0.6 + contrast * 0.25, 1)


def _ass(text, layout, font, accent, highlight):
    words = text.upper().split()
    lit = {w.upper() for w in (highlight or [])}
    body = " ".join(f"{{\\c{accent}}}{w}{{\\c&H00FFFFFF&}}" if re.sub(r"\W", "", w) in lit else w for w in words)
    if layout == "left":
        style, pos = f"T,{font},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,10,5,4,60,620,0,1", ""
        body = "\\N".join(" ".join(words[i:i + 2]) for i in range(0, len(words), 2)) if not lit else body
    elif layout == "band":
        style, pos = f"T,{font},96,&H00FFFFFF,&H00FFFFFF,&H002020D0,&H00000000,1,0,0,0,100,100,0,0,3,18,0,2,40,40,40,1", ""  # BorderStyle 3: OutlineColour is the box (red)
    else:
        style, pos = f"T,{font},150,{accent},{accent},&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,12,6,5,40,40,0,1", ""
    return ("[Script Info]\nScriptType: v4.00+\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: {style}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,9:00:00.00,T,,0,0,0,,{pos}{body}\n")


def _compose(bg, text, layout, font, accent, highlight, out, work):
    ass = Path(work) / f"thumb-{layout}.ass"
    ass.write_text(_ass(text, layout, font, accent, highlight), encoding="utf-8")
    # Darken the side the text sits on so it reads at feed size.
    shade = {"left": "drawbox=x=0:y=0:w=iw*0.55:h=ih:color=black@0.35:t=fill,",
             "band": "", "center": "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.25:t=fill,"}[layout]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.12:saturation=1.3,"
          f"unsharp=5:5:0.8,{shade}vignette=PI/5,subtitles='{_esc(ass)}'")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(bg), "-vf", vf, "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def make(meta, scenes, cat, language, work, out_dir):
    """Writes thumb_1..3.jpg and thumbnail.jpg (the pick) into out_dir; returns the pick's path."""
    from .render import font_for  # late import: render imports a lot

    work, out_dir = Path(work), Path(out_dir)
    font = font_for(language)
    accent = "&H0000D7FF&"
    text = (meta.get("thumb_text") or meta["title"]).strip()
    highlight = meta.get("thumb_highlight") or []

    candidates = []  # (score, path, label)
    if meta.get("thumb_prompt") and not settings.VISUALS_OFFLINE:
        got = visuals.ai_image(meta["thumb_prompt"], visuals.style_text(cat.get("style") or "cinematic"),
                               False, visuals.new_seed(), work / "thumb-ai")
        if got:
            candidates.append((_score(got[0]) + 10, got[0], "ai"))  # made for this job: small bonus
    for n, sc in enumerate([s for s in scenes if not s.get("brand")][:10]):
        src = sc.get("visual")
        if not src:
            continue
        if sc.get("kind") == "video":
            frame = work / f"thumbframe{n}.jpg"
            run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(src), "-frames:v", "1", str(frame)])
            src = frame
        try:
            candidates.append((_score(src), Path(src), f"scene {n + 1}"))
        except RuntimeError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    picks = candidates[:3]
    while len(picks) < 3:
        picks.append(picks[len(picks) % len(candidates)])

    made = []
    for i, ((score, bg, label), layout) in enumerate(zip(picks, LAYOUTS), start=1):
        out = _compose(bg, text, layout, font, accent, highlight, out_dir / f"thumb_{i}.jpg", work)
        made.append((score + (5 if layout == "left" else 0), out, f"{label}, {layout}"))
    made.sort(key=lambda m: -m[0])
    shutil.copy2(made[0][1], out_dir / "thumbnail.jpg")
    log.info("thumbnail: %s (others kept as thumb_1..3.jpg for Studio's Test & compare)", made[0][2])
    return out_dir / "thumbnail.jpg"
