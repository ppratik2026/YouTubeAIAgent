"""ffmpeg does all the work: one segment per scene (its picture held exactly as long as its voice),
then one final pass that adds narration, music and burned-in subtitles."""
import random
from pathlib import Path

from . import settings
from .util import duration, log, run

GAP = 0.35  # breath after each scene's line


def size(portrait):
    return (1080, 1920) if portrait else (1920, 1080)


def font_for(language):
    return "Noto Sans Devanagari" if language == "hi" else "Noto Sans"


def _scene_audio(mp3, dur, out):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-af", "apad", "-t", f"{dur:.3f}",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out)])


def _scene_video(src, kind, dur, portrait, n, out):
    w, h = size(portrait)
    enc = ["-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p",
           "-r", str(settings.FPS)]
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if kind == "video":
        run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.3f}",
             "-vf", f"{cover},fps={settings.FPS}", *enc, str(out)])
        return
    # Still image: a slow pan across a 12% larger copy, alternating direction, so it never sits dead.
    bw, bh = int(w * 1.12) // 2 * 2, int(h * 1.12) // 2 * 2
    moves = [f"x='(iw-{w})*t/{dur:.3f}':y='(ih-{h})/2'", f"x='(iw-{w})*(1-t/{dur:.3f})':y='(ih-{h})/2'",
             f"x='(iw-{w})/2':y='(ih-{h})*t/{dur:.3f}'", f"x='(iw-{w})/2':y='(ih-{h})*(1-t/{dur:.3f})'"]
    vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
          f"crop={w}:{h}:{moves[n % 4]},setsar=1")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(settings.FPS), "-i", str(src),
         "-t", f"{dur:.3f}", "-vf", vf, *enc, str(out)])


def _ts(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text):
    return text.replace("{", "(").replace("}", ")").replace("\\", "/").replace("\n", " ").strip()


def _chunks(text, per):
    words = text.split()
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)] or [text]


def subtitles(scenes, language, portrait, out):
    w, h = size(portrait)
    font = font_for(language)
    fs, margin, per = (78, 520, 4) if portrait else (58, 70, 7)
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{font},{fs},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,"
        f"60,60,{margin},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for sc in scenes:
        parts = _chunks(_clean(sc["narration"]), per)
        total = sum(len(p) for p in parts) or 1
        t = sc["start"]
        for p in parts:
            d = sc["speech"] * len(p) / total
            lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + d)},Sub,,0,0,0,,{p}")
            t += d
    Path(out).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return out


def _music(mood):
    for folder in (settings.MUSIC_DIR / mood, settings.MUSIC_DIR):
        if folder.is_dir():
            tracks = [p for p in folder.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")]
            if tracks:
                return random.choice(tracks)
    return None


def _ff_path(p):
    """Escape a path for use inside an ffmpeg filter argument."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render(scenes, language, portrait, mood, work, out_mp4):
    """scenes: [{narration, audio, visual, kind}] -> fills start/speech/dur, writes out_mp4."""
    work = Path(work)
    segs, wavs, t = [], [], 0.0
    for n, sc in enumerate(scenes):
        sc["speech"] = duration(sc["audio"])
        sc["dur"] = sc["speech"] + GAP
        sc["start"] = t
        t += sc["dur"]
        wav, seg = work / f"a{n:03d}.wav", work / f"v{n:03d}.mp4"
        _scene_audio(sc["audio"], sc["dur"], wav)
        _scene_video(sc["visual"], sc["kind"], sc["dur"], portrait, n, seg)
        wavs.append(wav)
        segs.append(seg)
        log.info("scene %s/%s %.1fs", n + 1, len(scenes), sc["dur"])

    for name, items in (("video.txt", segs), ("audio.txt", wavs)):
        (work / name).write_text("".join(f"file '{p.resolve()}'\n" for p in items), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "video.txt"),
         "-c", "copy", str(work / "visual.mp4")])
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "audio.txt"),
         "-c", "copy", str(work / "narration.wav")])
    subs = subtitles(scenes, language, portrait, work / "subs.ass")

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(work / "visual.mp4"), "-i", str(work / "narration.wav")]
    music = _music(mood)
    vf = f"[0:v]subtitles='{_ff_path(subs)}'[v]"
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        af = (f"[2:a]volume=0.12,afade=t=out:st={max(0, t - 2):.2f}:d=2[m];"
              "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        af = "[1:a]anull[a]"
    cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{t:.3f}",
            "-c:v", "libx264", "-preset", settings.X264_PRESET, "-crf", str(settings.VIDEO_CRF),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_mp4)]
    run(cmd)
    return t


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
          f"subtitles='{_ff_path(ass)}'")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(first_segment), "-vf", vf, "-frames:v", "1",
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
