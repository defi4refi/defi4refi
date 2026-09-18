#!/usr/bin/env python3
"""Free-tier enrichment: website email scrape (all orgs) + GitHub API has-devs (bounded)."""
import json, re, time, urllib.request, urllib.parse, socket

CH = "http://localhost:8123/"
socket.setdefaulttimeout(8)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
BAD_EMAIL = re.compile(r"(sentry|wixpress|example\.|\.png|\.jpg|\.webp|noreply@|no-reply@|@2x|@3x|schema\.|godaddy|w3\.org|domain)", re.I)

# target orgs: have domain AND (multi-source OR funding events OR artizen/karma/giveth)
orgs = rows_json("""
  SELECT org_id, canonical_name, domain, github, twitter, source_count
  FROM defi4refi.orgs FINAL
  WHERE domain != ''
""").copy()
print("orgs with domains:", len(orgs))

# ---- website scrape: homepage + /contact + /about (parallel) ----
from concurrent.futures import ThreadPoolExecutor

def scrape_org(o):
    dom = o["domain"]
    found = set()
    for path in ["", "/contact", "/about", "/contact-us"]:
        try:
            h = urllib.request.urlopen(urllib.request.Request(
                f"https://{dom}{path}", headers={"User-Agent": "Mozilla/5.0 (compatible; defi4refi)"}), timeout=8).read(400_000).decode("utf-8", "replace")
            for m in EMAIL_RE.findall(h):
                if not BAD_EMAIL.search(m):
                    found.add(m.lower())
        except Exception:
            pass
        if found:
            break
    out = [{"org_id": o["org_id"], "channel": "email", "value": e, "verified": 0, "source": "site-scrape"}
           for e in list(found)[:5]]
    if o["twitter"]:
        out.append({"org_id": o["org_id"], "channel": "twitter", "value": o["twitter"].split(",")[0], "verified": 0, "source": "resolve"})
    if o["github"]:
        out.append({"org_id": o["org_id"], "channel": "github", "value": o["github"].split(",")[0], "verified": 0, "source": "resolve"})
    return out

contacts = []
done = 0
with ThreadPoolExecutor(32) as ex:
    for out in ex.map(scrape_org, orgs):
        contacts.extend(out)
        done += 1
        if done % 300 == 0:
            print("scanned", done, "contacts:", len(contacts), flush=True)

q("INSERT INTO defi4refi.contacts FORMAT JSONEachRow", data="\n".join(json.dumps(c) for c in contacts))
print("contacts written:", len(contacts))

# ---- github has-devs (bounded by rate limit ~55/hr) ----
q("""CREATE TABLE IF NOT EXISTS defi4refi.org_github (
     org_id String, gh_org String, public_repos UInt32, last_push String,
     fetched_at DateTime DEFAULT now()) ENGINE = MergeTree ORDER BY org_id""")
gh_rows = []
cand = [o for o in orgs if o["github"]]
print("github candidates:", len(cand))
for o in cand[:55]:
    g = o["github"].split(",")[0].split("/")[0]
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"https://api.github.com/orgs/{g}", headers={"User-Agent": "defi4refi"}), timeout=8).read())
        gh_rows.append({"org_id": o["org_id"], "gh_org": g,
                        "public_repos": d.get("public_repos") or 0,
                        "last_push": (d.get("updated_at") or "")[:10]})
    except Exception as e:
        pass
    time.sleep(1.1)
if gh_rows:
    q("INSERT INTO defi4refi.org_github FORMAT JSONEachRow", data="\n".join(json.dumps(r) for r in gh_rows))
print("github enriched:", len(gh_rows))
print("DONE")
