#!/usr/bin/env python3
"""Read-only lead browser: static UI + /api proxy to ClickHouse."""
import json, re, urllib.parse, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

CH = "http://localhost:8123/"
ROOT = Path(__file__).parent
PORT = 8471


def ch_query(sql):
    req = urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql + " FORMAT JSONEachRow"),
        data=b"", method="POST")
    body = urllib.request.urlopen(req, timeout=60).read().decode()
    return [json.loads(l) for l in body.splitlines() if l.strip()]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        if self.path.startswith("/api?"):
            sql = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
            if not re.match(r"^\s*(SELECT|WITH|SHOW|DESCRIBE)\b", sql, re.I):
                return self._json({"error": "read-only"}, 403)
            try:
                return self._json({"rows": ch_query(sql)})
            except Exception as e:
                return self._json({"error": str(e)[:300]}, 500)
        if self.path == "/" or self.path == "/index.html":
            self.path = "/index.html"
        super().do_GET()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"lead browser → http://localhost:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
