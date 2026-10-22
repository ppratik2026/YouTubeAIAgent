#!/usr/bin/env python3
"""Run this ONCE on your own computer (it opens a browser) to get YT_REFRESH_TOKEN for .env.

    python3 scripts/get_refresh_token.py CLIENT_ID CLIENT_SECRET

The OAuth client must be of type "Desktop app". Standard library only - nothing to install.
"""
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube "
          "https://www.googleapis.com/auth/yt-analytics.readonly")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    client_id, client_secret = sys.argv[1], sys.argv[2]
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Done - you can close this tab and go back to the terminal.".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state})
    threading.Thread(target=server.handle_request, daemon=True).start()
    print("Opening the browser. Pick the Google account / channel to upload to.\n\nIf it does not open:\n" + url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        threading.Event().wait(0.5)
    if "error" in got:
        sys.exit(f"Google said: {got['error']}")
    data = urllib.parse.urlencode({"code": got["code"], "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data))
    if "refresh_token" not in tok:
        sys.exit(f"No refresh token returned: {tok}")
    print("\nPut these three lines in .env on the server:\n")
    print(f"YT_CLIENT_ID={client_id}\nYT_CLIENT_SECRET={client_secret}\nYT_REFRESH_TOKEN={tok['refresh_token']}")


if __name__ == "__main__":
    main()
