"""Quality gate before anything is uploaded. A weak or repetitive video hurts a channel more than a
missing one, so videos below the bar wait for you in `./yt review` instead of going out."""
import re

from . import settings, state

MAX_SIMILARITY = 0.30  # word-trigram overlap with an earlier script; above this it is a re-run


def _shingles(text, n=3):
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a, b):
    sa, sb = _shingles(a), _shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def most_similar(text, category, limit=60):
    """Highest overlap with the last `limit` scripts in this category, and which video it was."""
    best, title = 0.0, ""
    for e in [e for e in state.history() if e["category"] == category][-limit:]:
        f = settings.VIDEOS_DIR / e["dir"] / "script.txt"
        if f.exists():
            s = similarity(text, f.read_text(encoding="utf-8"))
            if s > best:
                best, title = s, e["title"]
    return best, title


def score(meta, scenes, hook, similar):
    """0-100 with the reasons, so `./yt review` can say what is wrong."""
    reasons = []
    hook_score = hook["score"]["verdict"] if hook else 60  # your own recording: no generated hook
    title_score = meta["title_options"][0]["score"] if meta.get("title_options") else 60
    real = sum(1 for s in scenes if s.get("visual") and s["visual"].suffix != ".png") / max(1, len(scenes))
    original = max(0.0, 1 - similar / MAX_SIMILARITY) if similar else 1.0
    total = round(0.30 * hook_score + 0.25 * title_score + 0.25 * real * 100 + 0.20 * original * 100)
    if hook_score < 50:
        reasons.append(f"weak hook ({hook_score})")
    if title_score < 50:
        reasons.append(f"weak title ({title_score})")
    if real < 0.8:
        reasons.append(f"{round((1 - real) * 100)}% scenes have no picture")
    if similar >= MAX_SIMILARITY:
        reasons.append(f"{round(similar * 100)}% same as an earlier video")
    return total, reasons
