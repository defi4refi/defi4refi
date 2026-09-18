#!/usr/bin/env python3
"""Contact waterfall for funded orgs:
 1) scrape known website fields -> emails/socials
 2) Wikidata name->domain for orgs without sites
 3) NIH RePORTER PI contacts (award detail fields)
 4) Reacher SMTP-verify inferred/found emails
"""
import json, re, subprocess, time, urllib.request, urllib.parse, socket, sys
from concurrent.futures import ThreadPoolExecutor

CH = "http://localhost:8123/"
REACHER = "/tmp/check_if_email_exists"
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
TW = re.compile(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{2,20})")
GH = re.compile(r"github\.com/([A-Za-z0-9_-]{2,39})(?:/|\b)")
BSKY = re.compile(r"(?:bsky\.app/profile/|@)([a-z0-9.-]+\.(?:bsky\.social|social|com|org|net|dev|earth|io))\b", re.I)
MASTODON = re.compile(r"@([a-z0-9_]+)@((?:mastodon|social|mstdn|fediverse|fosstodon|hachyderm|mas\.to|ecoevo|scicomm|green)[a-z0-9.-]*\.[a-z]{2,})", re.I)
RELME = re.compile(r'rel="me"[^>]*href="(https?://[^"]+)"', re.I)
NPUB = re.compile(r"\b(npub1[a-z0-9]{20,})\b")
FCAST = re.compile(r"warpcast\.com/([a-z0-9_.-]{2,30})", re.I)
MATRIX = re.compile(r"matrix\.to/#/([#!][a-z0-9_.:/-]+)", re.I)
TELE = re.compile(r"t\.me/([a-z0-9_]{3,32})", re.I)
DISCORD = re.compile(r"discord(?:\.gg|\.com/invite)/([a-z0-9]+)", re.I)
BIOLINK = re.compile(r"(?:linktr\.ee|linksta\.cc|carrd\.co|bio\.site|beacons\.ai|allmylinks\.com|withkoji\.com)/([a-z0-9_.-]{2,40})", re.I)
ENS = re.compile(r"\b([a-z0-9-]{3,}\.eth)\b", re.I)
FORM = re.compile(r'<form[^>]*action="([^"]*)"', re.I)

AI_CHANNELS = {"bluesky","mastodon","nostr","farcaster","matrix","github","form","telegram","discord","email","person"}
JUNK_EMAIL = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|css|js)$|example\.|sentry|wixpress|godaddy|u0026|@2x|@3x|noresponse|noreply|@company\.com|@domain\.com|^name@|^test@|^example@|^john@|^jane@|^user@|^placeholder@", re.I)

socket.setdefaulttimeout(10)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12).read(400_000).decode("utf-8", "replace")

def insert_contacts(rows):
    if rows:
        q("INSERT INTO defi4refi.contacts (org_id,channel,value,verified,source) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def add_contact(out, org_id, channel, value, source, verified=0):
    v = value.strip().lower().rstrip(".,;'\"")
    if channel == "email" and (JUNK_EMAIL.search(v) or len(v) > 80): return
    out.append({"org_id": org_id, "channel": channel, "value": v, "verified": verified, "source": source})

def reacher(email):
    try:
        r = subprocess.run([REACHER, email], capture_output=True, text=True, timeout=15)
        j = json.loads(r.stdout or "{}")
        return 1 if j.get("is_reachable") in ("safe",) else 0
    except Exception:
        return 0

# ================= STAGE 1: scrape known websites of funded orgs =================
def stage1_scrape():
    sites = rows_json("""
      SELECT m.org_id, l.website FROM defi4refi.lead_org_map m
      JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source
      WHERE l.website != ''
        AND l.website NOT LIKE '%usaspending.gov%' AND l.website NOT LIKE '%grants.gov%'
        AND l.website NOT LIKE '%propublica.org%' AND l.website NOT LIKE '%worldbank.org%'
        AND l.website NOT LIKE '%reporter.nih.gov%' AND l.website NOT LIKE '%nsf.gov%'
        AND m.org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
      GROUP BY m.org_id, l.website LIMIT 6000""")
    print("stage1 sites:", len(sites), flush=True)
    known = {(c["org_id"], c["channel"], c["value"]) for c in rows_json("SELECT org_id, channel, value FROM defi4refi.contacts")}
    out = []
    def scrape(s):
        base = s["website"].rstrip("/")
        found = []
        for path in ["", "/contact", "/contact-us", "/about", "/about-us", "/team"]:
            try:
                h = get(base + path)
                for e in set(EMAIL.findall(h)):
                    add_contact(found, s["org_id"], "email", e, "site-scrape")
                for t in set(TW.findall(h)):
                    add_contact(found, s["org_id"], "twitter", t, "site-scrape")
                for g in set(GH.findall(h)):
                    add_contact(found, s["org_id"], "github", g, "site-scrape")
                for m in set(BSKY.findall(h)):
                    add_contact(found, s["org_id"], "bluesky", m if m.startswith("@") else "@"+m, "site-scrape")
                for m in set(MASTODON.findall(h)):
                    add_contact(found, s["org_id"], "mastodon", "@"+m[0]+"@"+m[1], "site-scrape")
                for u in set(RELME.findall(h)):
                    if "mastodon" in u or "/@" in u or ".social" in u:
                        add_contact(found, s["org_id"], "mastodon", u, "rel-me")
                for n in set(NPUB.findall(h)):
                    add_contact(found, s["org_id"], "nostr", n, "site-scrape")
                for f in set(FCAST.findall(h)):
                    add_contact(found, s["org_id"], "farcaster", f, "site-scrape")
                for m in set(MATRIX.findall(h)):
                    add_contact(found, s["org_id"], "matrix", m, "site-scrape")
                for t in set(TELE.findall(h)):
                    add_contact(found, s["org_id"], "telegram", t, "site-scrape")
                for d in set(DISCORD.findall(h)):
                    add_contact(found, s["org_id"], "discord", d, "site-scrape")
                for b in set(BIOLINK.findall(h)):
                    add_contact(found, s["org_id"], "biolink", b, "site-scrape")
                for en in set(ENS.findall(h)):
                    add_contact(found, s["org_id"], "ens", en, "site-scrape")
                if path in ("/contact", "/contact-us"):
                    for f in set(FORM.findall(h))[:1]:
                        add_contact(found, s["org_id"], "form", f or base + path, "contact-form")
                if any(c["channel"] in ("email","bluesky","mastodon") for c in found):
                    break
            except Exception:
                continue
        return found
    with ThreadPoolExecutor(24) as ex:
        for i, r in enumerate(ex.map(scrape, sites)):
            out.extend(r)
            if (i + 1) % 200 == 0:
                print("stage1", i + 1, "sites,", len(out), "contacts", flush=True)
    out = [c for c in out if (c["org_id"], c["channel"], c["value"]) not in known]
    insert_contacts(out)
    print("stage1 done:", len(out), "NEW contacts")

# ================= STAGE 2: Wikidata name->domain =================
def stage2_wikidata():
    orgs = rows_json("""
      SELECT DISTINCT o.org_id, o.canonical_name FROM defi4refi.orgs o FINAL
      WHERE o.domain = ''
        AND o.org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
      LIMIT 500""")
    print("stage2 names:", len(orgs), flush=True)
    out = []
    for o in orgs:
        try:
            sparql = ('SELECT ?w WHERE { ?item rdfs:label "%s"@en . ?item wdt:P856 ?w } LIMIT 1'
                      % o["canonical_name"].replace('"', '\\"'))
            d = json.loads(get("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(sparql)))
            b = d["results"]["bindings"]
            if b:
                dom = urllib.parse.urlparse(b[0]["w"]["value"]).netloc.replace("www.", "")
                if dom:
                    add_contact(out, o["org_id"], "website", "https://" + dom, "wikidata")
        except Exception:
            pass
        time.sleep(0.3)
    insert_contacts(out)
    print("stage2 resolved:", len(out))

# ================= STAGE 3: NIH PI contacts =================
def stage3_nih():
    orgs = rows_json("""
      SELECT DISTINCT l.name, m.org_id FROM defi4refi.lead_org_map m
      JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source
      WHERE m.source='nih-reporter' AND m.org_id NOT IN (SELECT org_id FROM defi4refi.contacts)
      LIMIT 1000""")
    print("stage3 nih orgs:", len(orgs), flush=True)
    out = []
    for o in orgs[:400]:
        try:
            body = {"criteria": {"org_names": [o["name"].upper()]},
                    "limit": 5, "include_fields": ["ContactPiName", "Organization", "ProjectTitle", "AwardAmount"]}
            d = json.loads(get("https://api.reporter.nih.gov/v2/projects/search",
                               data=json.dumps(body).encode()))
            for p in (d.get("results") or [])[:3]:
                pi = p.get("contact_pi_name")
                if pi:
                    add_contact(out, o["org_id"], "person", pi.title(), "nih-pi")
        except Exception:
            pass
        time.sleep(0.3)
    insert_contacts(out)
    print("stage3 PIs:", len(out))

# ================= STAGE 4: handle fanout via Maigret =================
def stage4_fanout():
    """Existing github/twitter/ens handles -> maigret over 3k sites -> agent-reachable profiles."""
    handles = rows_json("""
      SELECT DISTINCT org_id, value FROM defi4refi.contacts
      WHERE channel IN ('github','twitter','ens') AND value != ''
      AND org_id IN (SELECT org_id FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap')
      LIMIT 300""")
    print("stage4 handles:", len(handles), flush=True)
    out = []
    for h in handles:
        handle = h["value"].lstrip("@").replace(".eth", "")
        if len(handle) < 3:
            continue
        try:
            r = subprocess.run(
                [sys.prefix + "/bin/python", "-m", "maigret", handle,
                 "--folderoutput", "/tmp/maigret", "--no-color", "-a", "--timeout", "8",
                 "--top-sites", "60", "--json", "simple"],
                capture_output=True, text=True, timeout=120)
            # maigret writes report json to folderoutput
            import glob, os
            reports = glob.glob("/tmp/maigret/report_*simple.json") or glob.glob("/tmp/maigret/*.json")
            for rp in reports[-1:]:
                try:
                    rep = json.load(open(rp))
                except Exception:
                    continue
                for site, d in rep.items():  # simple report: {site_name: {status:{status:...}, url_user:...}}
                    st = ((d.get("status") or {}).get("status") or "").upper()
                    if "CLAIM" not in st:
                        continue
                    url = d.get("url_user") or ""
                    if not url:
                        continue
                    ch = ("bluesky" if "bsky" in url else
                          "mastodon" if any(x in url for x in ("mastodon",".social/@","fosstodon","hachyderm","mas.to")) else
                          "nostr" if "nostr" in url or "npub" in url else
                          "farcaster" if "warpcast" in url else
                          "matrix" if "matrix.to" in url else
                          "telegram" if "t.me" in url else
                          "discord" if "discord" in url else
                          "github" if "github" in url else
                          "twitter" if "twitter" in url or "x.com" in url else
                          "substack" if "substack" in url else
                          "biolink" if "linktr" in url or "beacons" in url else
                          "social")
                    add_contact(out, h["org_id"], ch, url, f"maigret:{site}")
            for rp in reports:
                os.remove(rp)
        except Exception as e:
            print("fanout", handle, str(e)[:80])
    insert_contacts(out)
    print("stage4 fanout:", len(out))

if __name__ == "__main__":
    stages = {"scrape": stage1_scrape, "wikidata": stage2_wikidata, "nih": stage3_nih, "fanout": stage4_fanout}
    for a in (sys.argv[1:] or stages):
        stages[a]()
    print("WATERFALL DONE")
