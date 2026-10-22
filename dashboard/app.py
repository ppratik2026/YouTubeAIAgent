"""Web dashboard: everything ./yt does, from a phone.

Reads the JSON files in data/ directly; every change goes through the same CLI (`python -m pipeline`),
so the dashboard and ./yt can never disagree. Password-protected (HTTP basic auth) with a CSRF token on
every form. Put it behind HTTPS (see README) before opening the port to the internet.
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, redirect, render_template_string, request, send_file, url_for

from pipeline import settings

ROOT = settings.ROOT
SHARED = settings.SHARED_DIR
USER = os.environ.get("DASHBOARD_USER", "admin")
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
SECRET = (PASSWORD + str(SHARED)).encode()
SINGLE = "_"  # single-channel mode

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB uploads (recordings, songs)
_cache = {}


# ---------- helpers ----------

def channels():
    names = sorted(p.parent.name for p in (SHARED / "channels").glob("*/channel.json"))
    return names or [SINGLE]


def ddir(ch):
    if ch == SINGLE:
        return SHARED
    if ch not in channels():
        abort(404)
    return SHARED / "channels" / ch


def rj(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def cli(ch, *args, timeout=600):
    cmd = [sys.executable, "-m", "pipeline", *(["--channel", ch] if ch != SINGLE else []), *map(str, args)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    lines = [ln for ln in (p.stdout + p.stderr).splitlines() if " INFO " not in ln]
    return p.returncode, "\n".join(lines[-40:])


def cached(key, seconds, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def health(ch):
    def go():
        _, out = cli(ch, "health", timeout=120)
        rows = []
        for ln in out.splitlines():
            if ln.startswith(("ERROR", "warn")):
                rows.append({"level": "error" if ln.startswith("ERROR") else "warn", "msg": ln[6:].strip()})
        return rows
    return cached(f"health:{ch}", 60, go)


def csrf():
    return hmac.new(SECRET, b"csrf", hashlib.sha256).hexdigest()[:32]


def auth(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        au = request.authorization
        if not (au and hmac.compare_digest(au.username or "", USER)
                and hmac.compare_digest(au.password or "", PASSWORD)):
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="YouTube AI Agent"'})
        if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), csrf()):
            abort(403)
        return fn(*a, **k)
    return wrapper


def summary(ch):
    d = ddir(ch)
    q = rj(d / "queue.json", {"jobs": []})["jobs"]
    h = rj(d / "history.json", [])
    return {"name": ch, "label": rj(d / "channel.json", {}).get("name") or ("Main" if ch == SINGLE else ch),
            "to_make": sum(max(0, j["count"] - j["made"]) for j in q if j["status"] == "active"),
            "ready": sum(1 for e in h if e["status"] == "ready"),
            "review": sum(1 for e in h if e["status"] == "review"),
            "uploaded": sum(1 for e in h if e["status"] == "uploaded"),
            "views": sum(e.get("views", 0) for e in h)}


def options():
    cats = {k: v["label"] for k, v in rj(ROOT / "config/categories.json", {}).items() if not k.startswith("_")}
    styles = [k for k in rj(ROOT / "config/styles.json", {}) if not k.startswith("_")]
    edits = [k for k in rj(ROOT / "config/edits.json", {}) if not k.startswith("_")]
    return cats, styles, edits


def upcoming(ch, days=60):
    out = []
    for ev in rj(ROOT / "config/calendar.json", {}).get("events", []):
        chans = ev.get("channels") or ["*"]
        if "*" in chans or ch in chans:
            day = date.fromisoformat(ev["date"])
            if date.today() <= day <= date.today() + timedelta(days=days):
                out.append(ev)
    return out


# ---------- pages ----------

BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }} - YouTube AI Agent</title>
<style>
:root{--bg:#0f1115;--card:#181b22;--fg:#e8e8ea;--muted:#9aa0aa;--acc:#ffd23f;--err:#ff5d5d;--warn:#ffb020;--ok:#3ecf8e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
a{color:var(--acc)}header{padding:12px 16px;background:#000;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header a{color:var(--fg);text-decoration:none;font-weight:600}main{padding:16px;max-width:1100px;margin:auto}
.card{background:var(--card);border-radius:12px;padding:14px 16px;margin:0 0 14px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
h2{font-size:17px;margin:0 0 10px}.muted{color:var(--muted);font-size:13px}.n{font-size:22px;font-weight:700}
.err{border-left:4px solid var(--err)}.warn{border-left:4px solid var(--warn)}
label{display:block;font-size:13px;color:var(--muted);margin-top:8px}
input,select,textarea{width:100%;padding:9px;border-radius:8px;border:1px solid #333;background:#0b0d10;color:var(--fg);font:inherit}
button{background:var(--acc);color:#000;border:0;border-radius:8px;padding:9px 14px;font-weight:700;margin-top:10px;cursor:pointer}
button.ghost{background:#2a2f3a;color:var(--fg)}button.bad{background:var(--err);color:#fff}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 4px;border-bottom:1px solid #262a33;text-align:left;vertical-align:top}
video,img.t{width:100%;max-width:480px;border-radius:8px;background:#000}.thumbs img{width:31%;margin-right:2%;border-radius:6px;border:2px solid transparent}
.thumbs img.on{border-color:var(--acc)}.row{display:flex;gap:8px;flex-wrap:wrap}.row form{display:inline}
pre{white-space:pre-wrap;background:#0b0d10;padding:10px;border-radius:8px;font-size:12px;max-height:420px;overflow:auto}
.two{display:grid;gap:12px;grid-template-columns:1fr 1fr}@media(max-width:640px){.two{grid-template-columns:1fr}}
</style></head><body><header><a href="/">▶ YouTube AI Agent</a>
{% for c in chans %}<a href="/c/{{ c }}">{{ 'Main' if c == '_' else c }}</a>{% endfor %}</header><main>
{% if flash %}<div class="card"><pre>{{ flash }}</pre></div>{% endif %}
{{ body|safe }}</main></body></html>"""


def page(title, body_tpl, **ctx):
    body = render_template_string(body_tpl, csrf=csrf(), **ctx)
    return render_template_string(BASE, title=title, body=body, chans=channels(), flash=request.args.get("msg", ""))


def back(ch, msg=""):
    return redirect(url_for("channel", ch=ch, msg=msg[-1500:]))


@app.get("/")
@auth
def home():
    rows = [summary(c) for c in channels()]
    problems = [(c, p) for c in channels() for p in health(c)]
    q = rj(SHARED / f"quota-{hashlib.sha1(settings.YT_CLIENT_ID.encode()).hexdigest()[:8]}.json", {})
    g = rj(SHARED / "gemini_usage.json", {})
    return page("Home", """
{% for c, p in problems %}<div class="card {{ 'err' if p.level == 'error' else 'warn' }}">
<b>{{ 'Problem' if p.level == 'error' else 'Note' }}</b> ({{ 'Main' if c == '_' else c }}): {{ p.msg }}</div>{% endfor %}
<div class="grid">{% for r in rows %}<a class="card" href="/c/{{ r.name }}" style="text-decoration:none;color:inherit">
<h2>{{ r.label }}</h2><div class="row"><div><div class="n">{{ r.to_make }}</div><div class="muted">to make</div></div>
<div><div class="n">{{ r.review }}</div><div class="muted">review</div></div>
<div><div class="n">{{ r.ready }}</div><div class="muted">ready</div></div>
<div><div class="n">{{ r.uploaded }}</div><div class="muted">uploaded</div></div></div>
<div class="muted">{{ '{:,}'.format(r.views) }} views</div></a>{% endfor %}</div>
<div class="card muted">Uploads today: {{ q.get('uploads', 0) }} · Gemini calls today: {{ g.get('calls', 0) }}</div>
""", rows=rows, problems=problems, q=q, g=g)


@app.get("/c/<ch>")
@auth
def channel(ch):
    d = ddir(ch)
    cats, styles, edits = options()
    jobs = [j for j in rj(d / "queue.json", {"jobs": []})["jobs"] if j["status"] in ("active", "stopped")]
    hist = rj(d / "history.json", [])
    review = []
    for e in [e for e in hist if e["status"] == "review"][-10:]:
        m = rj(d / "videos" / e["dir"] / "meta.json", {})
        review.append(dict(e, notes=m.get("quality_notes") or [], similar=m.get("similar_to", "")))
    ready = [e for e in hist if e["status"] == "ready"][-10:]
    for e in ready:
        e["thumbs"] = sorted(p.name for p in (d / "videos" / e["dir"]).glob("thumb_*.jpg"))
    uploaded = [e for e in hist if e["status"] == "uploaded"][-15:][::-1]
    cm = [c for c in rj(d / "comments.json", {"items": {}})["items"].values() if c["status"] == "draft"][:20]
    return page(ch, """
{% for p in health %}<div class="card {{ 'err' if p.level == 'error' else 'warn' }}">{{ p.msg }}</div>{% endfor %}
<div class="two">
<form class="card" method="post" action="/c/{{ ch }}/add"><h2>Make videos</h2><input type="hidden" name="csrf" value="{{ csrf }}">
<label>Category</label><select name="category">{% for k, v in cats.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
<label>…or your own category</label><input name="custom" placeholder="e.g. cricket">
<div class="two"><div><label>Language</label><select name="lang"><option value="hi">Hindi</option><option value="en">English</option></select></div>
<div><label>Format</label><select name="format"><option value="short">Short</option><option value="long">Long</option></select></div></div>
<div class="two"><div><label>How many</label><input name="count" type="number" value="5" min="1" max="1000"></div>
<div><label>Minutes (long)</label><input name="minutes" type="number" value="8" min="1" max="60" step="0.5"></div></div>
<div class="two"><div><label>Voice</label><select name="voice"><option>male</option><option>female</option></select></div>
<div><label>Voice engine</label><select name="tts"><option value="">default</option><option value="edge">free Microsoft</option><option value="clone">my cloned voice</option></select></div></div>
<div class="two"><div><label>Picture style</label><select name="style"><option value="">category default</option>{% for s in styles %}<option>{{ s }}</option>{% endfor %}</select></div>
<div><label>Edit style</label><select name="edit"><option value="">default</option>{% for s in edits %}<option>{{ s }}</option>{% endfor %}</select></div></div>
<label>Also in another language (e.g. en:my_english_channel)</label><input name="also" placeholder="optional">
<button>Add to queue</button></form>

<form class="card" method="post" action="/c/{{ ch }}/record" enctype="multipart/form-data"><h2>Video from my audio</h2>
<input type="hidden" name="csrf" value="{{ csrf }}">
<label>Audio file (your voiceover, or your own song / bhajan)</label><input type="file" name="audio" accept="audio/*,video/mp4" required>
<label><input type="checkbox" name="song" style="width:auto"> It is a song / bhajan / instrumental</label>
<label>Lyrics (.lrc timed, or .txt) - songs only</label><input type="file" name="lyrics" accept=".lrc,.txt">
<label>What is it about (songs)</label><input name="title" placeholder="e.g. Shiv bhajan">
<label>Category</label><select name="category">{% for k, v in cats.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
<div class="two"><div><label>Language</label><select name="lang"><option value="hi">Hindi</option><option value="en">English</option></select></div>
<div><label>Format</label><select name="format"><option value="long">Long</option><option value="short">Short</option></select></div></div>
<button>Upload and make video</button></form></div>

{% if jobs %}<div class="card"><h2>Queue</h2><table><tr><th>Job</th><th>Made</th><th></th></tr>
{% for j in jobs %}<tr><td>{{ j.event or j.get('recording') or j.category }} · {{ j.language }} · {{ j.format }}{% if j.status == 'stopped' %} <b style="color:var(--err)">stopped</b>{% endif %}</td>
<td>{{ j.made }}/{{ j.count }}{% if j.failed %} ({{ j.failed }} failed){% endif %}</td>
<td><form method="post" action="/c/{{ ch }}/cancel/{{ j.id }}"><input type="hidden" name="csrf" value="{{ csrf }}"><button class="ghost">Cancel</button></form></td></tr>{% endfor %}</table></div>{% endif %}

{% for e in review %}<div class="card warn"><h2>Review: {{ e.title }}</h2>
<div class="muted">quality {{ e.quality }} · {{ e.notes|join('; ') }}{% if e.similar %} · looks like "{{ e.similar }}"{% endif %}</div>
<video controls preload="none" src="/media/{{ ch }}/{{ e.dir }}/video.mp4"></video>
<div class="row"><form method="post" action="/c/{{ ch }}/set/{{ e.id }}/ready"><input type="hidden" name="csrf" value="{{ csrf }}"><button>Approve</button></form>
<form method="post" action="/c/{{ ch }}/set/{{ e.id }}/rejected"><input type="hidden" name="csrf" value="{{ csrf }}"><button class="bad">Reject</button></form></div></div>{% endfor %}

{% if ready %}<div class="card"><h2>Ready to upload</h2>{% for e in ready %}<p><b>{{ e.title }}</b> <span class="muted">({{ e.format }}, {{ e.duration|int }}s)</span></p>
<video controls preload="none" src="/media/{{ ch }}/{{ e.dir }}/video.mp4"></video>
{% if e.thumbs %}<div class="thumbs">{% for t in e.thumbs %}<form method="post" action="/c/{{ ch }}/thumb/{{ e.dir }}/{{ t }}" style="display:inline">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="image" src="/media/{{ ch }}/{{ e.dir }}/{{ t }}" style="width:31%;border-radius:6px" title="Use this thumbnail"></form>{% endfor %}
<div class="muted">Tap a thumbnail to use it. Now: <img src="/media/{{ ch }}/{{ e.dir }}/thumbnail.jpg" style="width:80px;vertical-align:middle"></div></div>{% endif %}{% endfor %}</div>{% endif %}

{% if cm %}<div class="card"><h2>Comment replies</h2>{% for c in cm %}<form method="post" action="/c/{{ ch }}/reply/{{ c.id }}">
<input type="hidden" name="csrf" value="{{ csrf }}"><p class="muted">[{{ c.pile }}] {{ c.author }} on "{{ c.video_title[:50] }}"{% if c.pin %} · pin this{% endif %}</p>
<p>{{ c.text }}</p><textarea name="text" rows="2">{{ c.reply }}</textarea>
<div class="row"><button>Post reply</button><button class="ghost" name="skip" value="1">Skip</button></div></form>{% endfor %}</div>{% endif %}

<div class="two"><div class="card"><h2>Uploaded</h2><table>{% for e in uploaded %}<tr><td><a href="https://youtu.be/{{ e.youtube_id }}">{{ e.title[:60] }}</a>
<div class="muted">{{ e.format }} · {{ e.get('views', '–') }} views{% if e.retention %} · lost {{ e.retention.hook_leak }}% in 30s{% endif %}</div></td></tr>{% endfor %}</table></div>
<div class="card"><h2>Coming up</h2>{% for ev in events %}<p>{{ ev.date }} · {{ ev.name }} <span class="muted">({{ ev.format }} ×{{ ev.get('count', 1) }}, queued {{ ev.get('lead_days', 5) }} days before)</span></p>{% else %}<p class="muted">Nothing in config/calendar.json for the next 60 days.</p>{% endfor %}
<div class="row"><form method="post" action="/c/{{ ch }}/run/progress"><input type="hidden" name="csrf" value="{{ csrf }}"><button class="ghost">Monetization progress</button></form>
<form method="post" action="/c/{{ ch }}/run/comments"><input type="hidden" name="csrf" value="{{ csrf }}"><button class="ghost">Fetch comments</button></form>
<a href="/c/{{ ch }}/log"><button class="ghost" type="button">Log</button></a></div></div></div>
""", ch=ch, cats=cats, styles=styles, edits=edits, jobs=jobs, review=review, ready=ready, uploaded=uploaded,
                cm=cm, events=upcoming(ch), health=health(ch))


@app.post("/c/<ch>/add")
@auth
def add(ch):
    f = request.form
    cat = (f.get("custom") or "").strip() or f["category"]
    args = ["add", "--category", cat, "--lang", f["lang"], "--format", f["format"],
            "--count", max(1, min(1000, int(f.get("count") or 1))), "--minutes", f.get("minutes") or 8,
            "--voice", f.get("voice", "male")]
    for key in ("tts", "style", "edit"):
        if f.get(key):
            args += [f"--{key}", f[key]]
    if f.get("also", "").strip():
        args += ["--also", f["also"].strip()]
    _, out = cli(ch, *args)
    return back(ch, out)


@app.post("/c/<ch>/record")
@auth
def record(ch):
    inbox = ddir(ch) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    audio = request.files["audio"]
    name = Path(audio.filename or "audio.mp3").name.replace(" ", "_")
    audio.save(inbox / name)
    args = ["record", name, "--category", request.form["category"], "--lang", request.form["lang"],
            "--format", request.form["format"]]
    if request.form.get("song"):
        args.append("--song")
        if request.form.get("title"):
            args += ["--title", request.form["title"]]
        lyr = request.files.get("lyrics")
        if lyr and lyr.filename:
            lname = Path(lyr.filename).name.replace(" ", "_")
            lyr.save(inbox / lname)
            args += ["--lyrics", lname]
    _, out = cli(ch, *args)
    return back(ch, out)


@app.post("/c/<ch>/cancel/<job>")
@auth
def cancel(ch, job):
    return back(ch, cli(ch, "cancel", job)[1])


@app.post("/c/<ch>/set/<vid>/<status>")
@auth
def set_status(ch, vid, status):
    if status not in ("ready", "rejected"):
        abort(400)
    return back(ch, cli(ch, "approve" if status == "ready" else "reject", vid)[1])


@app.post("/c/<ch>/thumb/<folder>/<name>")
@auth
def pick_thumb(ch, folder, name):
    vdir = (ddir(ch) / "videos" / folder).resolve()
    src = (vdir / name).resolve()
    if src.parent != vdir or not name.startswith("thumb_") or not src.exists():
        abort(404)
    (vdir / "thumbnail.jpg").write_bytes(src.read_bytes())
    return back(ch, f"Thumbnail set to {name}")


@app.post("/c/<ch>/reply/<cid>")
@auth
def reply(ch, cid):
    if request.form.get("skip"):
        return back(ch, cli(ch, "reply-skip", cid)[1] or "skipped")
    return back(ch, cli(ch, "reply", cid, "--text", request.form.get("text", "").strip())[1])


@app.post("/c/<ch>/run/<what>")
@auth
def run_cmd(ch, what):
    cmds = {"progress": ["progress"], "comments": ["comments", "--fetch"]}
    if what not in cmds:
        abort(400)
    return back(ch, cli(ch, *cmds[what], timeout=300)[1])


@app.get("/c/<ch>/log")
@auth
def log_view(ch):
    f = ddir(ch) / "logs" / "pipeline.log"
    tail = f.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if f.exists() else []
    return page("Log", "<div class='card'><h2>Last 300 lines</h2><pre>{{ t }}</pre></div>", t="\n".join(tail))


@app.get("/media/<ch>/<folder>/<name>")
@auth
def media(ch, folder, name):
    vdir = (ddir(ch) / "videos").resolve()
    p = (vdir / folder / name).resolve()
    if vdir not in p.parents or p.suffix not in (".mp4", ".jpg") or not p.exists():
        abort(404)
    return send_file(p, conditional=True)  # Range requests, so the video player can seek


def main():
    if len(PASSWORD) < 8:
        # Wait instead of exiting, so docker does not restart-loop; .env changes need a restart anyway.
        print("Dashboard off: set DASHBOARD_PASSWORD (8+ characters) in .env, then: docker compose up -d",
              flush=True)
        while True:
            time.sleep(3600)
    from waitress import serve
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    print(f"dashboard on :{port} (user {USER})", flush=True)
    serve(app, host="0.0.0.0", port=port, threads=6)


if __name__ == "__main__":
    main()
