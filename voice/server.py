"""Voice-clone service: speaks any text in the voice of a sample file, on the CPU, free.

Model: Chatterbox Multilingual by Resemble AI (MIT licence, Hindi + English + more), zero-shot -
a 10-30 second clean sample of the speaker is enough, no training.

    POST /tts   {"text": "...", "language": "hi", "voice": "male"}  -> audio/wav
    GET  /health                                                    -> {"ok": true, "voices": [...]}

Samples live in DATA_DIR/voices/<voice>.wav (or .mp3). Only clone a voice whose owner agreed.
"""
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import soundfile
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

DATA = Path(os.environ.get("DATA_DIR", "/app/data"))
VOICES = DATA / "voices"
torch.set_num_threads(os.cpu_count() or 4)
print("loading Chatterbox Multilingual (first start downloads the model once)...", flush=True)
MODEL = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
LOCK = threading.Lock()  # one generation at a time; the CPU is the bottleneck anyway
CURRENT = {}  # which voice sample the model is conditioned on right now
print("voice service ready", flush=True)


EXTS = (".wav", ".mp3", ".m4a", ".flac", ".ogg")


def sample(voice):
    """'female' -> data/voices/female.wav; 'bhakti/female' -> data/channels/bhakti/voices/female.wav,
    falling back to the shared one."""
    ch, _, name = voice.rpartition("/")
    folders = ([DATA / "channels" / ch / "voices"] if ch else []) + [VOICES]
    for folder in folders:
        for ext in EXTS:
            p = folder / f"{name}{ext}"
            if p.exists():
                return p
    return None


def all_voices():
    names = {p.stem for p in VOICES.glob("*") if p.suffix in EXTS}
    for p in DATA.glob("channels/*/voices/*"):
        if p.suffix in EXTS:
            names.add(f"{p.parent.parent.name}/{p.stem}")
    return sorted(names)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, json.dumps({"ok": True, "voices": all_voices()}).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.path != "/tts":
            return self._send(404, b"{}")
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            ref = sample(req.get("voice", "male"))
            if not ref:
                return self._send(400, json.dumps({"error": f"no sample for voice {req.get('voice')}"}).encode())
            exaggeration = float(req.get("exaggeration", 0.5))
            with LOCK, torch.inference_mode():
                # Reading the sample is slow; do it once per voice, not once per sentence.
                key = (str(ref), ref.stat().st_mtime, exaggeration)
                if CURRENT.get("key") != key:
                    MODEL.prepare_conditionals(str(ref), exaggeration=exaggeration)
                    CURRENT["key"] = key
                wav = MODEL.generate(req["text"], language_id=req.get("language", "hi"),
                                     exaggeration=exaggeration, cfg_weight=float(req.get("cfg_weight", 0.5)))
            buf = io.BytesIO()
            soundfile.write(buf, wav.squeeze(0).cpu().numpy(), MODEL.sr, format="WAV")
            self._send(200, buf.getvalue(), "audio/wav")
        except Exception as e:  # noqa: BLE001 - report to the caller, keep serving
            self._send(500, json.dumps({"error": str(e)[:500]}).encode())

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
