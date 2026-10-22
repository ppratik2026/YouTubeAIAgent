"""Topic -> hooks -> script -> packaging, following the yt-script, yt-package and yt-seo skills."""
import random

from . import settings, trends
from .llm import ask_json
from .skills import formulas_brief, lint_title, rules, score_hook
from .util import log

WPM = 150  # the yt-script skill's runtime estimate

LANG = {
    "hi": ("Hindi", "Write all spoken text in natural, everyday spoken Hindi in Devanagari script "
                    "(common English words like 'phone', 'police', 'video' are fine). Not formal/shuddh Hindi."),
    "en": ("English", "Write all spoken text in simple, clear English that an Indian audience follows easily."),
}


def _lang(language):
    return LANG.get(language, LANG["en"])


# Different video shapes, rotated so the channel never looks templated (YouTube's "inauthentic /
# mass-produced content" rule is about exactly that).
STRUCTURES = [
    "story arc: set-up, rising tension, twist, resolution, the lesson",
    "countdown: a numbered list, best saved for last, each item with a concrete example",
    "myth vs reality: what people believe, then what is actually true, point by point",
    "case file: timeline of what happened, the key moment, what we still do not know",
    "question-led: the viewer's real question, three wrong answers people give, the right one",
    "explainer: the one idea, a simple analogy, a real example, what it means for the viewer",
    "before / after: how it was, what changed, why, what comes next",
]


def _channel_block():
    ch = settings.load_channel()
    if not ch:
        return ""
    host = ch.get("host", {})
    lines = [f"CHANNEL: {ch.get('name', '')} - {ch.get('niche', '')}. Audience: {ch.get('audience', '')}."]
    if host.get("name"):
        lines.append(f"HOST: the narrator is {host['name']}, {host.get('personality', '')}. Speak in first "
                     "person as this host; the same person in every video.")
    if ch.get("point_of_view"):
        lines.append(f"VALUE: {ch['point_of_view']}")
    if ch.get("avoid"):
        lines.append("AVOID: " + "; ".join(ch["avoid"]))
    if host.get("signature_open"):
        lines.append(f"The host's usual opening line (after the hook): {host['signature_open']}")
    if host.get("signature_close"):
        lines.append(f"The host's usual sign-off: {host['signature_close']}")
    return "\n".join(lines) + "\n"


def _system(cat, language):
    name, how = _lang(language)
    return (
        "You write YouTube videos that people finish. Follow these rules from the yt-script skill:\n\n"
        f"{rules('yt-script')}\n\n"
        f"{_channel_block()}"
        f"CATEGORY: {cat['label']}. {cat['tone']}\n"
        f"LANGUAGE: {name}. {how}\n"
        "ORIGINALITY: write it fresh for this channel. Add the host's own explanation, an example or "
        "comparison, and a takeaway - never just read out a summary. Vary sentence rhythm; no stock "
        "filler phrases.\n"
        "Image prompts and stock-footage search queries are ALWAYS in English.\n"
        "Never invent a number, a statistic, a quote or a source. No hateful, sexual or graphic content. "
        "No real living person may be shown as doing something they did not do.\n"
        "Reply with JSON only."
    )


def pick_structure(recent):
    """A structure not used in the last few videos of this category."""
    fresh = [s for s in STRUCTURES if s not in recent[-3:]] or STRUCTURES
    return random.choice(fresh)


# ---------- 1. topic ----------

def pick_topic(cat, language, video_format, used_titles, performance=None):
    used = {t.lower() for t in used_titles}
    if cat.get("news"):
        for story in trends.news_stories(cat.get("news_query", ""), language):
            if story["title"].lower() in used:
                continue
            facts = trends.story_facts(story["title"], language) or [story]
            return {"topic": story["title"], "angle": "", "facts": facts, "source_title": story["title"]}
        raise RuntimeError("no new news story found (all recent ones already made)")

    outliers = trends.youtube_outliers(cat["label"], language, video_format)
    inspo = "\n".join(f"- {v['title']} ({v['multiple']}x, {v['formula']})" for v in outliers) or "(none)"
    recent = "\n".join(f"- {t}" for t in list(used_titles)[-60:]) or "(none)"
    prompt = (
        f"Give ONE new {('YouTube Short' if video_format == 'short' else 'long YouTube video')} idea "
        f"for the category '{cat['label']}'.\n\n"
        f"What is working right now (ranked by how far each beat the others; learn the SHAPE, never copy "
        f"the story):\n{inspo}\n\nAlready made on this channel - do not repeat these:\n{recent}\n\n"
        f"{performance or ''}"
        'JSON: {"topic": "one line, in English", "angle": "why someone clicks, one line"}'
    )
    idea = ask_json(prompt, _system(cat, language), offline=lambda: {
        "topic": f"Test story {random.randint(1000, 9999)} for {cat['label']}", "angle": "test"})
    idea["facts"] = []
    return idea


def _facts_block(topic):
    if not topic["facts"]:
        return ""
    lines = "\n".join(f"- [{f['source']}] {f['title']}. {f['summary']}" for f in topic["facts"])
    return f"\n\nFACTS (use ONLY these; if something is not here, do not say it):\n{lines}\n"


# ---------- 2. hooks ----------

def best_hook(cat, language, video_format, topic, recent_formulas=()):
    avoid = ", ".join(sorted(set(recent_formulas))) or "none"
    prompt = (
        f"Topic: {topic['topic']}\nAngle: {topic.get('angle', '')}{_facts_block(topic)}\n"
        f"Write FIVE different opening hooks (the first {'3' if video_format == 'short' else '15'} seconds), "
        f"each on a different formula from this list:\n{formulas_brief()}\n"
        f"Used in the last videos, so prefer others: {avoid}\n\n"
        'JSON: {"hooks": [{"text": "the hook in the video language", '
        '"english": "the same hook in English", "formula": "formula name"}]}'
    )
    out = ask_json(prompt, _system(cat, language), offline=lambda: {"hooks": [
        {"text": "क्या आप जानते हैं ये बात?" if language == "hi" else "You have been doing this wrong.",
         "english": "You have been doing this wrong for 10 years, and it costs you.", "formula": "The Mistake"},
        {"text": "Test hook two", "english": "Here is the one thing nobody tells you.", "formula": "The Insider"},
    ]})
    hooks = out.get("hooks") or []
    if not hooks:
        raise RuntimeError("model returned no hooks")
    # hookscore.py is built on English patterns, so the English version is what gets scored.
    for h in hooks:
        h["score"] = score_hook(h.get("english") or h["text"])
    # Same opening formula video after video is a template; nudge towards a different one.
    rank = lambda h: h["score"]["verdict"] - (8 if h["score"]["formula"] in recent_formulas else 0)  # noqa: E731
    hooks.sort(key=rank, reverse=True)
    log.info("hook: %s (%s, %s)", hooks[0]["english"], hooks[0]["score"]["verdict"], hooks[0]["score"]["formula"])
    return hooks


# ---------- 3. script ----------

SCENE_JSON = ('{"narration": "1-2 spoken sentences", "emphasis": ["1-2 key words copied exactly from the '
              'narration, highlighted in the captions"], "visual_query": "2-4 English words to search '
              'stock footage", "image_prompt": "one detailed English sentence describing the picture"}')


CHARACTERS_JSON = ('"characters": [{"name": "short name used in scenes", "look": "fixed appearance in English: '
                   'age, gender, face, hair, skin tone, body, exact clothes and colours, one signature detail"}]')
CAST_RULE = ("This video uses AI pictures, so the same people must look the same in every picture: define each "
             "recurring character ONCE in \"characters\", and in every scene list who is in the shot in "
             "\"cast\" (names only). Image prompts describe action, place and emotion - not the looks.\n")


def _cast(cat):
    return cat.get("visuals") == "ai"


def _offline_scenes(n, language):
    line = ("यह एक टेस्ट वाक्य है जो वीडियो की आवाज़ और सबटाइटल जाँचने के लिए है।" if language == "hi"
            else "This is a test sentence to check the voice and the subtitles of the video.")
    return [{"narration": line, "visual_query": "city night", "image_prompt": "a city at night"} for _ in range(n)]


def write_short(cat, language, topic, hook, structure, parent=None, lessons=""):
    scene_json = SCENE_JSON[:-1] + ', "cast": ["names"]}' if _cast(cat) else SCENE_JSON
    cast = CAST_RULE if _cast(cat) else ""
    top = f"{CHARACTERS_JSON}, " if _cast(cat) else ""
    words = 130
    from_long = (f"This Short is cut from the channel's full video. Its script:\n{parent[:3500]}\n"
                 "Pick ONE moment that works on its own (yt-shorts skill), retell it fresh, and end with a "
                 "line that makes them want the full video ('full video on the channel').\n" if parent else "")
    prompt = (
        f"Write a YouTube SHORT (vertical, about {words} spoken words, 40-55 seconds).\n"
        f"Topic: {topic['topic']}\nAngle: {topic.get('angle', '')}{_facts_block(topic)}\n{from_long}"
        f"Shape: {structure}\n{lessons}"
        f"Start with exactly this hook: {hook['text']}\n"
        "6-9 scenes. The last line must loop back into the first line. No 'subscribe' talk.\n"
        f"{cast}"
        f'JSON: {{{top}"sections": [{{"heading": "Short", "scenes": [{scene_json}]}}]}}'
    )
    return ask_json(prompt, _system(cat, language),
                    offline=lambda: {"sections": [{"heading": "Short", "scenes": _offline_scenes(6, language)}]})


def write_long(cat, language, topic, hook, minutes, structure, lessons=""):
    words = int(minutes * WPM)
    scene_json = SCENE_JSON[:-1] + ', "cast": ["names"]}' if _cast(cat) else SCENE_JSON
    cast = CAST_RULE if _cast(cat) else ""
    top = f"{CHARACTERS_JSON}, " if _cast(cat) else ""
    n_sections = max(3, min(10, round(minutes / 1.5)))
    outline = ask_json(
        f"Plan a {minutes}-minute YouTube video (~{words} spoken words) in {n_sections} sections.\n"
        f"Topic: {topic['topic']}\nAngle: {topic.get('angle', '')}{_facts_block(topic)}\n"
        f"The hook is: {hook['text']}\nShape of the video: {structure}\n{lessons}"
        "Put an open question early that is only answered near the end, and a small re-hook every 2-3 "
        "minutes so people stay (watch time is what grows the channel).\n"
        "Section 1 is the hook + the turn (say what the video will do, no channel intro). The last section "
        "is the payoff + ONE ask. Every section has one idea.\n"
        f"{cast}"
        f'JSON: {{{top}"sections": [{{"heading": "3-5 word chapter title in the video language", '
        '"beats": "what happens in this section, 2-3 lines, English", "words": 0}]}',
        _system(cat, language),
        offline=lambda: {"sections": [{"heading": f"भाग {i + 1}" if language == "hi" else f"Part {i + 1}",
                                       "beats": "test", "words": words // n_sections} for i in range(n_sections)]},
        temperature=0.7)
    characters = outline.get("characters") or []
    who = ("Characters (use these names in \"cast\"): " + ", ".join(c["name"] for c in characters) + "\n"
           if characters else "")
    sections, story_so_far = [], []
    for i, sec in enumerate(outline["sections"]):
        target = int(sec.get("words") or words // len(outline["sections"]))
        first = f"Start with exactly this hook: {hook['text']}\n" if i == 0 else ""
        out = ask_json(
            f"Write section {i + 1} of {len(outline['sections'])} of a YouTube video.\n"
            f"Topic: {topic['topic']}{_facts_block(topic)}\n"
            f"Whole plan: {[s['heading'] for s in outline['sections']]}\n"
            f"This section: {sec['heading']} - {sec['beats']}\n"
            f"Already said (do not repeat): {' '.join(story_so_far)[-1500:]}\n{first}"
            f"About {target} spoken words, split into scenes of 1-2 sentences.\n{lessons}{who}"
            f'JSON: {{"scenes": [{scene_json}]}}',
            _system(cat, language),
            offline=lambda: {"scenes": _offline_scenes(4, language)},
            temperature=0.8)
        scenes = [s for s in out.get("scenes", []) if s.get("narration", "").strip()]
        sections.append({"heading": sec["heading"], "scenes": scenes})
        story_so_far += [s["narration"] for s in scenes]
    return {"sections": sections, "characters": characters}


# ---------- 4. packaging ----------

def package(cat, language, video_format, topic, script, about=""):
    full = " ".join(s["narration"] for sec in script["sections"] for s in sec["scenes"]).strip()
    full = (f"{about}\n{full}" if about else full) or topic["topic"]
    prompt = (
        f"{rules('yt-package')}\n\n{rules('yt-seo')}\n\n"
        f"The video ({'YouTube Short' if video_format == 'short' else 'long video'}): {full[:3000]}\n\n"
        "Write TEN title options (each with its own thumbnail text, max 3 words, different words from the "
        "title), in the video language. Then the description: the first two lines say what the viewer gets "
        "in the words they would search; then 3-5 short lines more. Then up to 12 tags (spellings, names, "
        "the words people type). Then the 3 search queries this should win. Then one English image prompt "
        "for the thumbnail background: a close-up subject with a strong emotion or a striking object, high "
        "contrast, bright colours, the left half kept simple for big text, no words in the image.\n"
        'JSON: {"titles": [{"title": "...", "thumb": "...", "highlight": ["the one thumbnail word to colour"]}], '
        '"description": "...", "tags": ["..."], "queries": ["..."], "thumb_prompt": "..."}'
    )
    out = ask_json(prompt, _system(cat, language), temperature=0.8, offline=lambda: {
        "titles": [{"title": f"{topic['topic'][:50]} - 3 things nobody told you", "thumb": "NOBODY SAW"},
                   {"title": "Amazing incredible test video title", "thumb": "test video"}],
        "description": "Test description line one.\nLine two.", "tags": ["test"], "queries": ["test"]})
    ranked = []
    for t in out.get("titles", []):
        title = t["title"].strip()[:100]
        if video_format == "short" and "#shorts" not in title.lower():
            title = (title[:91] + " #Shorts") if len(title) > 91 else title + " #Shorts"
        r = lint_title(title, t.get("thumb"))
        ranked.append({"title": title, "thumb": t.get("thumb", ""), "score": r["score"],
                       "highlight": t.get("highlight") or [], "issues": [m for _, m in r["issues"]]})
    if not ranked:
        raise RuntimeError("model returned no titles")
    ranked.sort(key=lambda r: -r["score"])
    log.info("title: %s (%s)", ranked[0]["title"], ranked[0]["score"])
    tags = [t.strip()[:30] for t in out.get("tags", []) if t.strip()][:12]
    return {"title": ranked[0]["title"], "thumb_text": ranked[0]["thumb"], "title_options": ranked[:3],
            "thumb_highlight": ranked[0]["highlight"], "thumb_prompt": out.get("thumb_prompt", ""),
            "description": out.get("description", "").strip(), "tags": tags, "queries": out.get("queries", [])}


# ---------- helpers for images and recordings ----------

def safe_image_prompt(prompt):
    """Reword an image prompt that a generator refused: same scene, nothing graphic, no real people."""
    try:
        out = ask_json(
            "An image generator refused this prompt, most likely its safety filter. Rewrite it to show the "
            "same moment safely: no blood, injury, weapons pointed at people, nudity, children in danger, "
            "or real named people - suggest it with mood, shadows, objects and setting instead.\n"
            f"Prompt: {prompt}\nJSON: {{\"prompt\": \"the new prompt, English, one sentence\"}}",
            "You rewrite image prompts. Reply with JSON only.",
            offline=lambda: {"prompt": prompt}, temperature=0.4)
        return out.get("prompt", "").strip()
    except Exception as e:  # noqa: BLE001 - a failed rewrite just means: try the next image source
        log.warning("prompt rewrite failed: %s", e)
        return ""


def visuals_for_transcript(cat, language, scenes, about=""):
    """For your own recording or song: pick a picture for every scene of what is heard."""
    numbered = "\n".join(f"{i + 1}. {s['narration'] or '(music only)'}" for i, s in enumerate(scenes))
    about = f"It is about: {about}\n" if about else ""
    out = ask_json(
        f"These are the scenes of a recorded {_lang(language)[0]} audio, in order:\n{numbered}\n{about}\n"
        "Pictures should follow the words; for music-only parts keep the mood with calm, beautiful scenes "
        "that change slowly.\n"
        f"For EVERY scene give the picture that should be on screen. Return exactly {len(scenes)} items.\n"
        f'JSON: {{"scenes": [{{"visual_query": "2-4 English words to search stock footage", '
        f'"image_prompt": "one detailed English sentence describing the picture"}}], '
        f'"sections": [{{"heading": "3-5 word chapter title in the video language", "first_scene": 1}}]}}',
        _system(cat, language), temperature=0.6,
        offline=lambda: {"scenes": [{"visual_query": "city", "image_prompt": "a city"} for _ in scenes],
                         "sections": [{"heading": "Start", "first_scene": 1}]})
    vis = out.get("scenes", [])
    for i, s in enumerate(scenes):
        v = vis[i] if i < len(vis) else (vis[-1] if vis else {})
        s["visual_query"] = v.get("visual_query", "abstract background")
        s["image_prompt"] = v.get("image_prompt", s["visual_query"])
    secs = sorted({max(1, min(len(scenes), int(x.get("first_scene", 1)))): x.get("heading", "")
                   for x in out.get("sections", [])}.items())
    if not secs or secs[0][0] != 1:
        secs.insert(0, (1, "Intro"))
    sections = []
    for k, (start, heading) in enumerate(secs):
        end = secs[k + 1][0] - 1 if k + 1 < len(secs) else len(scenes)
        sections.append({"heading": heading, "scenes": scenes[start - 1:end]})
    return {"sections": [s for s in sections if s["scenes"]]}
