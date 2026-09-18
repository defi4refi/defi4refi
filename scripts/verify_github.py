#!/usr/bin/env python3
"""Email MX verification + keyless GitHub org scrape (repos count via HTML)."""
import json, re, time, urllib.request, urllib.parse, socket
from concurrent.futures import ThreadPoolExecutor
import dns.resolver

CH = "http://localhost:8123/"
socket.setdefaulttimeout(10)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

# ---- 1. MX verification for scraped emails ----
emails = rows_json("SELECT org_id, value FROM defi4refi.contacts WHERE channel='email' AND verified=0")
print("emails to verify:", len(emails))
dom_cache = {}
def mx_ok(email):
    dom = email.split("@")[-1]
    if dom not in dom_cache:
        try:
            dom_cache[dom] = len(dns.resolver.resolve(dom, "MX", lifetime=6)) > 0
        except Exception:
            try:
                dom_cache[dom] = len(dns.resolver.resolve(dom, "A", lifetime=5)) > 0
            except Exception:
                dom_cache[dom] = False
    return dom_cache[dom]

upd = []
with ThreadPoolExecutor(24) as ex:
    for e, ok in zip(emails, ex.map(lambda c: mx_ok(c["value"]), emails)):
        if ok:
            upd.append({"org_id": e["org_id"], "channel": "email", "value": e["value"], "verified": 1, "source": "mx-check"})
q("INSERT INTO defi4refi.contacts FORMAT JSONEachRow", data="\n".join(json.dumps(u) for u in upd))
print("MX-verified:", len(upd), "/", len(emails))

# ---- 2. GitHub org scrape (no API limit) ----
orgs = rows_json("""SELECT org_id, github FROM defi4refi.orgs FINAL
  WHERE github != '' AND org_id NOT IN (SELECT org_id FROM defi4refi.org_github)""")
print("github orgs to scrape:", len(orgs))

def scrape_gh(o):
    g = o["github"].split(",")[0].split("/")[0]
    try:
        h = urllib.request.urlopen(urllib.request.Request(
            f"https://github.com/orgs/{g}/repositories",
            headers={"User-Agent": "Mozilla/5.0"}), timeout=10).read(300_000).decode("utf-8", "replace")
        m = re.search(r'"totalCount"\s*:\s*(\d+)', h) or re.search(r'(\d+)\s*(?:public\s*)?repositories', h)
        return {"org_id": o["org_id"], "gh_org": g,
                "public_repos": int(m.group(1)) if m else -1, "last_push": ""}
    except Exception:
        return None

gh = []
with ThreadPoolExecutor(16) as ex:
    for i, r in enumerate(ex.map(scrape_gh, orgs)):
        if r:
            gh.append(r)
        if (i + 1) % 100 == 0:
            print("gh scraped", i + 1, flush=True)
if gh:
    q("INSERT INTO defi4refi.org_github FORMAT JSONEachRow", data="\n".join(json.dumps(g) for g in gh))
print("github enriched:", len(gh), "DONE")
