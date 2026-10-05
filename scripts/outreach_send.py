#!/usr/bin/env python3
"""Send approved drafts via agent-reachable protocols.
Bluesky: @atproto-compatible XRPC — post-mention (reply/DM needs session).
Needs env: BSKY_HANDLE, BSKY_APP_PASSWORD (create at bsky.app -> Settings -> App Passwords).
Inbound: POST /inbound on :8899 -> replies table (Postal inbound route target)."""
import json, os, re, urllib.request, urllib.parse, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CH = os.environ.get("CH_URL", "http://localhost:8123/")

# load scripts/.env (gitignored) if present
_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k, _v)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

# ---------- Bluesky sender ----------
def bsky_send():
    handle = os.environ.get("BSKY_HANDLE", "")
    pw = os.environ.get("BSKY_APP_PASSWORD", "")
    if not handle or not pw:
        print("BSKY_HANDLE / BSKY_APP_PASSWORD not set — drafts staged only")
        return
    sess = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        data=json.dumps({"identifier": handle, "password": pw}).encode(),
        headers={"Content-Type": "application/json"}), timeout=20).read())
    token, did = sess["accessJwt"], sess["did"]
    sent = 0
    for d in rows_json("SELECT org_id, contact, open_line, body FROM defi4refi.drafts WHERE channel='bluesky' AND approved=1 AND org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log)"):
        # normalize: stored values may be @handle, bare handle, or bsky.app URL
        target = d["contact"].lstrip("@")
        if "bsky.app/profile/" in target:
            target = target.split("bsky.app/profile/")[-1].strip("/")
        if not re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", target):
            print("bsky skip bad handle:", d["contact"]); continue
        text = f"@{target} {d['open_line']} {d['body']}"[:290]
        # find handle facet for mention
        try:
            tgt = json.loads(urllib.request.urlopen(
                f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={target}", timeout=10).read())
            rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": __import__('datetime').datetime.utcnow().isoformat()+"Z",
                   "facets": [{"index": {"byteStart": 0, "byteEnd": len("@"+target)},
                               "features": [{"$type": "app.bsky.richtext.facet#mention", "did": tgt["did"]}]}]}
            req = urllib.request.Request("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                data=json.dumps({"repo": did, "collection": "app.bsky.feed.post", "record": rec}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            urllib.request.urlopen(req, timeout=15)
            q("INSERT INTO defi4refi.outreach_log FORMAT JSONEachRow",
              data=json.dumps({"org_id": d["org_id"], "channel": "bluesky", "value": target, "status": "sent"}))
            sent += 1
        except Exception as e:
            print("bsky send fail", target, str(e)[:80])
    print("bsky sent:", sent)

# ---------- inbound webhook (Postal route -> replies) ----------
class Inbound(BaseHTTPRequestHandler):
    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(ln).decode("utf-8", "replace")
        try:
            j = json.loads(body)
            frm = j.get("from", ""); msg = (j.get("plain_body") or j.get("html") or "")[:4000]
        except Exception:
            frm, msg = "", body[:4000]
        # match sender email back to org
        m = rows_json(f"SELECT org_id FROM defi4refi.contacts WHERE channel='email' AND lower(value)='{frm.lower()}' LIMIT 1")
        oid = m[0]["org_id"] if m else "?"
        q("INSERT INTO defi4refi.replies FORMAT JSONEachRow",
          data=json.dumps({"org_id": oid, "channel": "email", "value": frm, "body": msg, "reply_class": "", "reply_conf": 0}))
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

if __name__ == "__main__":
    import sys
    if "serve" in sys.argv:
        print("inbound webhook on :8899")
        HTTPServer(("127.0.0.1", 8899), Inbound).serve_forever()
    else:
        bsky_send()
