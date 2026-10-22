"""Bridge to the youtube-agent-skill pack in .claude/skills: its rules go into the prompts and its
Python tools (hookscore, title linter, hook formulas) do the scoring, exactly as the skills say."""
import importlib.util
import json
import re

from .settings import SKILLS_DIR


def _module(rel, name):
    spec = importlib.util.spec_from_file_location(name, SKILLS_DIR / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hookscore = _module("yt-script/hookscore.py", "hookscore")
title_lint = _module("yt-package/title.py", "title_lint")
HOOKS = json.loads((SKILLS_DIR / "yt-script" / "hooks.json").read_text(encoding="utf-8"))


def rules(skill):
    """The body of a SKILL.md minus its front matter, the 'voice.md' step (we have no voice file on
    a server) and the copy-paste gate (the pipeline is the one publishing)."""
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    text = re.sub(r"## The gate.*", "", text, flags=re.S)
    text = re.sub(r"1\. Read `~/.claude/youtube/voice.md`.*?read it out loud\.\n", "", text, flags=re.S)
    return text.strip()


def formulas_brief():
    return "\n".join(f"- {h['name']}: {h['shape']} e.g. \"{h['example']}\" Fails when: {h['fails_when']}"
                     for h in HOOKS["hooks"])


def score_hook(text):
    parts, verdict, name, _ = hookscore.score(text)
    return {"verdict": verdict, "band": hookscore.band(verdict), "formula": name, "parts": parts}


def lint_title(title, thumb=None):
    return title_lint.check(title, thumb)
