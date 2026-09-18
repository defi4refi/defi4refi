#!/usr/bin/env python3
"""Name->domain resolution for funded orgs without sites.
wbsearchentities -> wbgetentities P856 (official website) -> contacts(channel='website')."""
import json, re, time, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"
UA = {"User-Agent": "defi4refi/1.0 (lead-research)"}

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def getj(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15).read())

def clean(nm):
    nm = re.sub(r"│.*$", "", nm)  # strip │suffix from wrapped names
    nm = re.sub(r"\b(inc|llc|ltd|corp|corporation|co\.?|gmbh|pty|sarl|bv)\b\.?", "", nm, flags=re.I)
    nm = re.sub(r"[^a-zA-Z0-9 &'-]", " ", nm).strip()
    return re.sub(r"\s+", " ", nm)

def resolve(name):
    c = clean(name)
    if len(c) < 4:
        return None
    d = getj("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&limit=3&search=" + urllib.parse.quote(c))
    for hit in (d.get("search") or []):
        label = (hit.get("label") or "").lower()
        # loose match: shared prefix or containment either way
        if not (clean(label).lower()[:8] == c.lower()[:8] or clean(label).lower() in c.lower() or c.lower() in clean(label).lower()):
            continue
        e = getj("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&ids=%s&props=claims" % hit["id"])
        claims = (e.get("entities") or {}).get(hit["id"], {}).get("claims", {})
        for p in claims.get("P856", []):
            url = p["mainsnak"]["datavalue"]["value"]
            dom = urllib.parse.urlparse(url if url.startswith("http") else "https://" + url).netloc.replace("www.", "")
            if dom and "." in dom:
                return "https://" + dom
    return None

orgs = rows_json("""
  SELECT DISTINCT o.org_id, o.canonical_name FROM defi4refi.orgs o FINAL
  WHERE o.domain = ''
    AND o.org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
    AND o.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='website')
    AND length(splitByChar(' ', canonical_name)) >= 2
    AND NOT match(canonical_name, '/')
    AND length(canonical_name) >= 8
  LIMIT %d""" % int(sys.argv[1] if len(sys.argv) > 1 else 3000))
print("resolving domains for", len(orgs), "orgs", flush=True)

out, found = [], 0
for i, o in enumerate(orgs):
    try:
        site = resolve(o["canonical_name"])
        if site:
            out.append({"org_id": o["org_id"], "channel": "website", "value": site, "verified": 0, "source": "wikidata"})
            found += 1
    except Exception:
        pass
    if (i + 1) % 100 == 0:
        print(i + 1, "→", found, "domains", flush=True)
        if out:
            q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
              data="\n".join(json.dumps(r) for r in out)); out = []
    time.sleep(0.7)
if out:
    q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
      data="\n".join(json.dumps(r) for r in out))
print("DOMAIN RESOLVE DONE:", found, "/", len(orgs))
