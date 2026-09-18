#!/usr/bin/env python3
"""Bulk email verification: Reacher CLI parallel over unverified email contacts."""
import json, subprocess, sys, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

CH = "http://localhost:8123/"
REACHER = "/tmp/check_if_email_exists"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

emails = rows_json("""
  SELECT DISTINCT org_id, value FROM defi4refi.contacts
  WHERE channel='email' AND verified=0
  LIMIT %d""" % int(sys.argv[1] if len(sys.argv) > 1 else 2000))
print("verifying", len(emails), flush=True)

def verify(e):
    try:
        r = subprocess.run([REACHER, e["value"]], capture_output=True, text=True, timeout=20)
        j = json.loads(r.stdout or "{}")
        ok = 1 if j.get("is_reachable") == "safe" else 0
        return (e["org_id"], e["value"], ok)
    except Exception:
        return (e["org_id"], e["value"], 0)

done = 0
buf = []
with ThreadPoolExecutor(8) as ex:
    for oid, em, ok in ex.map(verify, emails):
        buf.append({"org_id": oid, "channel": "email", "value": em, "verified": ok, "source": "reacher-verify"})
        done += 1
        if done % 100 == 0:
            q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
              data="\n".join(json.dumps(r) for r in buf)); buf = []
            print(done, "/", len(emails), flush=True)
if buf:
    q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
      data="\n".join(json.dumps(r) for r in buf))
print("VERIFY DONE")
