#!/usr/bin/env python3
"""owner/repo-style funded orgs -> github owner profile -> email/blog/twitter/org."""
import json, re, time, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"
UA = {"User-Agent": "defi4refi/1.0"}

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def getj(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15).read())

def ins(rows):
    if rows:
        q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

# funded orgs whose canonical name is owner/repo style (web3/github-native projects)
orgs = rows_json("""
  SELECT org_id, canonical_name FROM defi4refi.orgs FINAL
  WHERE match(canonical_name, '^[A-Za-z0-9_-]{2,39}/[A-Za-z0-9._-]{2,100}$')
    AND org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
    AND org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='github' AND source='gh-owner')
  LIMIT %d""" % int(sys.argv[1] if len(sys.argv) > 1 else 2000))
print("gh-owner candidates:", len(orgs), flush=True)

out = []
for i, o in enumerate(orgs):
    owner = o["canonical_name"].split("/")[0]
    try:
        u = getj(f"https://api.github.com/users/{owner}")
        oid = o["org_id"]
        out.append({"org_id": oid, "channel": "github", "value": owner, "verified": 1, "source": "gh-owner"})
        for ch, fld in [("email","email"),("website","blog"),("twitter","twitter_username"),("mastodon","mastodon_username")]:
            v = (u.get(fld) or "").strip()
            if v:
                out.append({"org_id": oid, "channel": ch, "value": v if ch!="website" or v.startswith("http") else "https://"+v, "verified": 0, "source": "gh-owner"})
        if u.get("type") == "Organization":
            try:
                oj = getj(f"https://api.github.com/orgs/{owner}")
                if oj.get("email"):
                    out.append({"org_id": oid, "channel": "email", "value": oj["email"], "verified": 0, "source": "gh-owner-org"})
            except Exception:
                pass
    except Exception:
        pass
    if (i + 1) % 200 == 0:
        print(i + 1, "/", len(orgs), "→", len(out), "contacts", flush=True)
        ins(out); out = []
    time.sleep(0.5)
ins(out)
print("GH-OWNER DONE")
