#!/usr/bin/env python3
"""Enrich v2 — SOTA methods:
 A) JSON-LD sameAs + security.txt/humans.txt on known sites
 B) OpenAlex institution search -> homepage for research orgs (name->domain)
 C) Bluesky searchActors -> org-name->handle (keyless)
"""
import json, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

CH = "http://localhost:8123/"
UA = {"User-Agent": "defi4refi/1.0 (contact-research)"}
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
JUNK = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|css|js)$|example\.|sentry|@2x|@3x|noreply", re.I)
SAMEAS = re.compile(r'"sameAs"\s*:\s*\[([^\]]+)\]', re.I)
SOC = {"bsky": "bluesky", "mastodon": "mastodon", "fosstodon": "mastodon", "hachyderm": "mastodon",
       "mas.to": "mastodon", "warpcast": "farcaster", "github": "github", "twitter": "twitter",
       "x.com": "twitter", "t.me": "telegram", "discord": "discord", "linkedin": "linkedin",
       "instagram": "instagram", "youtube": "youtube", "nostr": "nostr"}

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def get(url, timeout=10):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read(300000).decode("utf-8", "replace")

def ins(rows):
    if rows:
        q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def add(out, oid, ch, val, src, verified=0):
    v = val.strip().lower().rstrip(".,;'\"/")
    if ch == "email" and (JUNK.search(v) or len(v) > 80): return
    if len(v) < 3: return
    out.append({"org_id": oid, "channel": ch, "value": v, "verified": verified, "source": src})

def chan_from_url(u):
    for k, ch in SOC.items():
        if k in u:
            return ch
    return "website"

# ---------- A) JSON-LD sameAs + well-known files on known sites ----------
def stage_sites():
    sites = rows_json("""
      SELECT DISTINCT org_id, value AS site FROM defi4refi.contacts
      WHERE channel='website' AND value LIKE 'http%'
      UNION ALL
      SELECT DISTINCT m.org_id, l.website AS site FROM defi4refi.lead_org_map m
      JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source
      WHERE l.website LIKE 'http%' AND l.website NOT LIKE '%usaspending%' AND l.website NOT LIKE '%nsf.gov%'
        AND l.website NOT LIKE '%reporter.nih%' AND l.website NOT LIKE '%propublica%' AND l.website NOT LIKE '%worldbank%'
        AND l.website NOT LIKE '%grants.gov%' AND l.website NOT LIKE '%opencollective.com%'
      LIMIT 4000""")
    print("sites:", len(sites), flush=True)
    known = {(c["org_id"], c["channel"], c["value"]) for c in rows_json(
        "SELECT org_id, channel, value FROM defi4refi.contacts WHERE source IN ('jsonld','security-txt','humans-txt')")}
    out = []
    def work(s):
        base = s["site"].rstrip("/")
        dom = urllib.parse.urlparse(base).netloc
        found = []
        try:
            h = get(base)
            for blob in SAMEAS.findall(h):
                for u in re.findall(r'"(https?://[^"]+)"', blob):
                    add(found, s["org_id"], chan_from_url(u), u, "jsonld")
            for e in set(EMAIL.findall(h)):
                add(found, s["org_id"], "email", e, "jsonld")
        except Exception:
            pass
        for wf in ["/.well-known/security.txt", "/humans.txt"]:
            try:
                t = get("https://" + dom + wf, timeout=8)
                for e in set(EMAIL.findall(t))[:3]:
                    add(found, s["org_id"], "email", e, "security-txt" if "security" in wf else "humans-txt")
            except Exception:
                pass
        return found
    with ThreadPoolExecutor(24) as ex:
        for i, r in enumerate(ex.map(work, sites)):
            out.extend(r)
            if (i + 1) % 300 == 0:
                print("sites", i + 1, "→", len(out), flush=True)
    out = [c for c in out if (c["org_id"], c["channel"], c["value"]) not in known]
    ins(out)
    print("sites done:", len(out))

# ---------- B) OpenAlex name->domain for funded research orgs ----------
def stage_openalex():
    orgs = rows_json("""
      SELECT DISTINCT o.org_id, o.canonical_name FROM defi4refi.orgs o FINAL
      WHERE o.domain = '' AND length(canonical_name) >= 8
        AND NOT match(canonical_name, '/')
        AND o.org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
        AND o.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='website' AND source='openalex')
      LIMIT 4000""")
    print("openalex orgs:", len(orgs), flush=True)
    out = []
    for i, o in enumerate(orgs):
        try:
            d = json.loads(get("https://api.openalex.org/institutions?search=" + urllib.parse.quote(o["canonical_name"][:80])))
            for inst in (d.get("results") or [])[:1]:
                if inst.get("homepage_url"):
                    dom = urllib.parse.urlparse(inst["homepage_url"]).netloc.replace("www.", "")
                    if dom:
                        add(out, o["org_id"], "website", "https://" + dom, "openalex")
                        if inst.get("ror"):
                            add(out, o["org_id"], "ror", inst["ror"], "openalex")
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print("openalex", i + 1, "→", len(out), flush=True)
            ins(out); out = []
        time.sleep(0.15)
    ins(out)
    print("openalex done:", len(out))

# ---------- C) Bluesky searchActors ----------
def stage_bsky():
    orgs = rows_json("""
      SELECT DISTINCT o.org_id, o.canonical_name FROM defi4refi.orgs o FINAL
      WHERE o.org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
        AND o.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='bluesky')
        AND length(canonical_name) >= 5 AND NOT match(canonical_name, '/')
      LIMIT 2000""")
    print("bsky orgs:", len(orgs), flush=True)
    out = []
    for i, o in enumerate(orgs):
        try:
            d = json.loads(get("https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors?q=" +
                               urllib.parse.quote(o["canonical_name"][:50]) + "&limit=3"))
            for a in (d.get("actors") or []):
                lbl = (a.get("displayName") or a.get("handle") or "").lower()
                nm = o["canonical_name"].lower()
                if nm[:10] in lbl or lbl[:10] in nm:
                    add(out, o["org_id"], "bluesky", "@" + a["handle"], "bsky-search")
                    if a.get("description"):
                        for e in EMAIL.findall(a["description"]):
                            add(out, o["org_id"], "email", e, "bsky-bio")
                    break
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print("bsky", i + 1, "→", len(out), flush=True)
            ins(out); out = []
        time.sleep(0.25)
    ins(out)
    print("bsky done:", len(out))

if __name__ == "__main__":
    stages = {"sites": stage_sites, "openalex": stage_openalex, "bsky": stage_bsky}
    for a in (sys.argv[1:] or stages):
        stages[a]()
    print("ENRICH2 DONE")
