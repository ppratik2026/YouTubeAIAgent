"""The editor. ffmpeg does all the work, free and licence-clean - CapCut-style edits made from its own
filters, not CapCut's files:

  per scene   picture held exactly as long as its line; Ken Burns zoom / pan, punch-zoom at the cut
  between     xfade transitions (fade, slide, wipe, circle, blur, ...) timed on the cut
  whole       colour grade, vignette, film grain, progress bar, animated captions (clean / box / pop /
              karaoke, key words highlighted), whoosh on transitions, music ducked under the voice,
              loudness normalised to YouTube's -14 LUFS

Editing styles live in config/edits.json. Everything is one final encode, so quality is not lost twice.
"""
import json
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import settings
from .util import duration, log, run

GAP = 0.35  # breath after each scene's line
EDITS = json.loads((settings.ROOT / "config" / "edits.json").read_text(encoding="utf-8"))
SFX_DIR = settings.ROOT / "assets" / "sfx"

GRADES = {
    "none": "",
    "cinematic": "eq=contrast=1.06:saturation=1.08,colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.05",
    "warm": "colortemperature=temperature=5200,eq=saturation=1.06",
    "cold": "colortemperature=temperature=8800,eq=contrast=1.05:saturation=0.9",
    "vintage": "curves=preset=vintage,eq=saturation=0.9",
    "bw": "hue=s=0,eq=contrast=1.12",
    "vivid": "eq=contrast=1.05:saturation=1.25",
}


def edit_style(name):
    style = dict(EDITS.get("simple"))
    style.update(EDITS.get(name) or {})
    style["name"] = name if name in EDITS else "simple"
    return style


def size(portrait):
    return (1080, 1920) if portrait else (1920, 1080)


def font_for(language):
    return "Noto Sans Devanagari" if language == "hi" else "Noto Sans"


# ---------- per scene ----------

def _scene_audio(src, dur, out):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", "apad", "-t", f"{dur:.3f}",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out)])


def _zoom_expr(motion, z, frames, punch):
    """zoompan expressions for one motion; `on` is the output frame number."""
    p = f"/{max(1, frames - 1)}"
    zoom = {"zoomin": f"1+{z}*on{p}", "zoomout": f"1+{z}-{z}*on{p}"}.get(motion, f"1+{z}")
    if punch:  # quick 6% bump that settles in a quarter second: the CapCut "punch in" at a cut
        zoom += f"+0.06*max(0,1-on/{settings.FPS * 0.25:.1f})"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    free_x, free_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
    x, y = {
        "panleft": (f"{free_x}*on{p}", cy), "panright": (f"{free_x}*(1-on{p})", cy),
        "panup": (cx, f"{free_y}*(1-on{p})"), "pandown": (cx, f"{free_y}*on{p}"),
    }.get(motion, (cx, cy))
    return zoom, x, y


def _look(style):
    """(grade, per-frame look). The grade is colour only, so on a still image it is applied once to the
    picture instead of to every frame - by far the slowest filter otherwise."""
    grade = GRADES.get(style["grade"], "")
    post = ",".join(f for f in ("vignette=PI/5" if style["vignette"] else "",
                                f"noise=alls={int(style['grain'])}:allf=t" if style["grain"] else "") if f)
    return grade, post


def _scene_video(src, kind, dur, portrait, out, style, motion):
    w, h = size(portrait)
    fps = settings.FPS
    frames = max(1, round(dur * fps))
    zoom, x, y = _zoom_expr(motion, style["zoom"], frames, style["punch"])
    grade, post = _look(style)
    post = f",{post}" if post else ""
    enc = ["-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps)]
    if kind == "video":
        # Footage already moves: cover the frame, a gentle zoom, and the punch at the cut.
        vz, _, _ = _zoom_expr("zoomin", style["zoom"] / 3, frames, style["punch"])
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},"
              f"zoompan=z='{vz.replace('on', 'in')}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps},"
              f"{grade + ',' if grade else ''}setsar=1{post}")
        run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.3f}",
             "-vf", vf, *enc, str(out)])
        return motion
    # Still image: upscale first (zoompan jitters on small images), then move across it.
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"{grade + ',' if grade else ''}"
          f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},setsar=1{post}")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-frames:v", str(frames), *enc, str(out)])
    return motion


# ---------- captions ----------

def _ts(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text):
    return text.replace("{", "(").replace("}", ")").replace("\\", "/").replace("\n", " ").replace("*", "").strip()


def _chunks(text, per):
    words = text.split()
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)]


HIGHLIGHT = "&H0000D7FF&"  # amber (ASS colours are BGR)


def _emphasise(chunk, keys):
    """Numbers and the scene's key words in amber; the rest stays white."""
    out = []
    for word in chunk.split():
        bare = re.sub(r"[^\w]", "", word).lower()
        if bare and (any(c.isdigit() for c in bare) or bare in keys):
            out.append(f"{{\\c{HIGHLIGHT}}}{word}{{\\c&H00FFFFFF&}}")
        else:
            out.append(word)
    return " ".join(out)


def subtitles(scenes, language, portrait, out, mode="clean"):
    w, h = size(portrait)
    font = font_for(language)
    fs, margin = (82, 560) if portrait else (60, 70)
    per = {"pop": 3 if portrait else 5, "karaoke": 8}.get(mode, 4 if portrait else 7)
    border, back, primary, secondary = 1, "&H80000000", "&H00FFFFFF", "&H00FFFFFF"
    if mode == "box":
        border, back = 3, "&H90000000"
    if mode == "karaoke":
        primary, secondary = "&H0000D7FF", "&H00FFFFFF"  # sung words fill amber
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{font},{fs},{primary},{secondary},&H00000000,{back},1,0,0,0,100,100,0,0,{border},5,2,2,"
        f"60,60,{margin},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for sc in scenes:
        text = _clean(sc["narration"])
        if not text:
            continue
        emph = sc.get("emphasis") or []
        keys = {re.sub(r"[^\w]", "", k).lower() for k in (emph if isinstance(emph, list) else str(emph).split())}
        parts = _chunks(text, per)
        total = sum(len(p) for p in parts) or 1
        t = sc["start"]
        for p in parts:
            d = sc["speech"] * len(p) / total
            if mode == "karaoke":
                words = p.split()
                wtotal = sum(len(x) for x in words) or 1
                body = "".join(f"{{\\k{max(1, round(d * 100 * len(x) / wtotal))}}}{x} " for x in words).strip()
            elif mode == "pop":
                body = "{\\fad(60,0)\\fscx72\\fscy72\\t(0,140,\\fscx100\\fscy100)}" + _emphasise(p, keys)
            else:
                body = _emphasise(p, keys)
            lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + d)},Sub,,0,0,0,,{body}")
            t += d
    Path(out).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------- audio helpers ----------

def _music(mood):
    for folder in (settings.MUSIC_DIR / mood, settings.MUSIC_DIR):
        if folder.is_dir():
            tracks = [p for p in folder.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")]
            if tracks:
                return random.choice(tracks)
    return None


def _whoosh(work):
    """Your own assets/sfx/whoosh*.wav|mp3 if present, else one synthesised from filtered noise."""
    if SFX_DIR.is_dir():
        own = sorted(p for p in SFX_DIR.glob("whoosh*") if p.suffix.lower() in (".wav", ".mp3"))
        if own:
            return own[0]
    out = Path(work) / "whoosh.wav"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.5:r=44100",
         "-af", "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.22,afade=t=out:st=0.22:d=0.23,volume=0.35",
         "-ac", "2", str(out)])
    return out


def _ff_path(p):
    """Escape a path for use inside an ffmpeg filter argument."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------- the edit ----------

def render(scenes, language, portrait, mood, work, out_mp4, gap=GAP, music=True, style="cinematic"):
    """scenes: [{narration, audio, visual, kind, emphasis?}] -> fills start/speech/dur, writes out_mp4."""
    work = Path(work)
    st = edit_style(style)
    rng = random.Random(str(out_mp4))
    w, h = size(portrait)
    T = float(st["transition_seconds"])
    segs, wavs, t = [], [], 0.0
    for n, sc in enumerate(scenes):
        sc["speech"] = duration(sc["audio"])
        sc["dur"] = sc["speech"] + gap
        sc["start"] = t
        t += sc["dur"]
    if T > 0:  # no transition can be longer than half the shortest scene
        T = min(T, min(sc["dur"] for sc in scenes) / 2)
    def one(n):
        sc = scenes[n]
        # Each picture runs T longer than its line so the next transition has something to blend from;
        # the audio is not stretched, so voice and picture stay in sync.
        extra = T if n < len(scenes) - 1 else 0.0
        _scene_audio(sc["audio"], sc["dur"], wavs[n])
        _scene_video(sc["visual"], sc["kind"], sc["dur"] + extra, portrait, segs[n], st, sc["motion"])
        log.info("scene %s/%s %.1fs %s", n + 1, len(scenes), sc["dur"], sc["motion"])

    for n, sc in enumerate(scenes):
        sc["motion"] = rng.choice(st["motion"])
        wavs.append(work / f"a{n:03d}.wav")
        segs.append(work / f"v{n:03d}.mp4")
    # Scenes are independent: render them on all cores at once.
    with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 2)) as pool:
        list(pool.map(one, range(len(scenes))))
    total = t

    (work / "audio.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in wavs), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "audio.txt"),
         "-c", "copy", str(work / "narration.wav")])
    subs = subtitles(scenes, language, portrait, work / "subs.ass", st["captions"])

    # Inputs: segments, narration, [music], [whoosh]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for s in segs:
        cmd += ["-i", str(s)]
    i_voice = len(segs)
    cmd += ["-i", str(work / "narration.wav")]
    track = _music(mood) if music and st["music_volume"] > 0 else None
    i_music = i_sfx = None
    if track:
        i_music = i_voice + 1
        cmd += ["-stream_loop", "-1", "-i", str(track)]
    cuts = [sc["start"] for sc in scenes[1:]] if st["sfx"] and T > 0 else []
    if cuts:
        i_sfx = (i_music or i_voice) + 1
        cmd += ["-i", str(_whoosh(work))]

    fc = []
    # video: transitions
    if T > 0 and len(segs) > 1:
        prev = "0:v"
        for k, sc in enumerate(scenes[1:], start=1):
            label = f"x{k}"
            trans = rng.choice(st["transitions"])
            fc.append(f"[{prev}][{k}:v]xfade=transition={trans}:duration={T:.3f}:offset={sc['start']:.3f}[{label}]")
            prev = label
        vlast = prev
    else:
        fc.append("".join(f"[{k}:v]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[cat]")
        vlast = "cat"
    # (grade, vignette and grain are already in each scene)
    if st["progress"]:
        fc.append(f"color=c=0xFFD700:s={w}x12:r={settings.FPS}[bar]")
        fc.append(f"[{vlast}][bar]overlay=x='-W+W*t/{total:.3f}':y=H-12:shortest=1[prog]")
        vlast = "prog"
    fc.append(f"[{vlast}]subtitles='{_ff_path(subs)}',format=yuv420p[v]")

    # audio: voice, music ducked under it, whooshes on the cuts, loudness to YouTube's target
    mix = []
    if track:
        fc.append(f"[{i_voice}:a]asplit=2[voice][key]")
        fc.append(f"[{i_music}:a]volume={st['music_volume']},afade=t=out:st={max(0, total - 2):.2f}:d=2[mus]")
        fc.append("[mus][key]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[duck]")
        mix += ["[voice]", "[duck]"]
    else:
        mix.append(f"[{i_voice}:a]")
    if cuts:
        fc.append(f"[{i_sfx}:a]asplit={len(cuts)}" + "".join(f"[w{k}]" for k in range(len(cuts))))
        for k, c in enumerate(cuts):
            ms = max(0, int((c - 0.2) * 1000))
            fc.append(f"[w{k}]adelay={ms}|{ms}[wd{k}]")
            mix.append(f"[wd{k}]")
    fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
              "loudnorm=I=-14:TP=-1.5:LRA=11[a]")

    script = work / "filter.txt"  # long graphs go in a file; the command line has a length limit
    script.write_text(";\n".join(fc), encoding="utf-8")
    cmd += ["-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", settings.X264_PRESET, "-crf", str(settings.VIDEO_CRF),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_mp4)]
    run(cmd)
    log.info("edit: %s (%s transitions, %s captions, grade %s)", st["name"],
             "no" if T == 0 else f"{T:.2f}s", st["captions"], st["grade"])
    return total


def thumbnail(first_segment, text, language, out_jpg, work):
    """1280x720 frame from the opening scene with the thumbnail text (max 3 words) on it.
    Text goes through libass so Hindi is shaped correctly."""
    ass = Path(work) / "thumb.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: T,{font_for(language)},120,&H0000F0FF,&H0000F0FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,1,9,4,1,"
        "50,50,50,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,9:00:00.00,T,,0,0,0,,{_clean(text).upper()}\n", encoding="utf-8")
    vf = (f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,eq=contrast=1.12:saturation=1.25,"
          f"vignette=PI/5,subtitles='{_ff_path(ass)}'")
    run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(first_segment), "-vf", vf, "-frames:v", "1",
         "-q:v", "3", str(out_jpg)])
    return out_jpg


def chapters(section_starts, total):
    """YouTube only renders chapters when: first at 0:00, at least 3, each at least 10 s."""
    pts = []
    for title, start in section_starts:
        if pts and start - pts[-1][1] < 10:
            continue
        pts.append((title, 0.0 if not pts else start))
    if pts and total - pts[-1][1] < 10:
        pts.pop()
    if len(pts) < 3:
        return ""

    def mmss(s):
        s = int(s)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    return "\n".join(f"{mmss(s)} {title}" for title, s in pts)
