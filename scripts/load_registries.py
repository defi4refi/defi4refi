#!/usr/bin/env python3
"""Traditional-org loaders -> defi4refi.raw_leads. Free APIs only.
Each source = config + thin normalizer; inserts via JSONEachRow."""
import json, re, time, urllib.request, urllib.parse, socket

CH = "http://localhost:8123/"
socket.setdefaulttimeout(15)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def insert(rows):
    if rows:
        q("INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def row(source, name, category="", raised=0.0, website="", chain="", notes="", priority=""):
    return {"source": source, "name": name, "category": category, "raised_usd": float(raised or 0),
            "website": website, "chain": chain, "notes": notes[:900], "priority": priority}

def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data,
        headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

ENV = re.compile(r"environ|conserv|climat|forest|reforest|ocean|water|solar|energy|green|sustain|biodiv|wildlife|nature|agro|ecolog|recycl|carbon|marine|habitat|wetland|reef|earth|planet", re.I)
TECH = re.compile(r"developer|software|engineer|data|gis|geospatial|digital|ict|programmer|devops|web|full.?stack|backend|frontend|database|tech|monitoring|mrv|sensor|remote sens", re.I)

# ---------- ProPublica Nonprofit Explorer (US 990s, env NTEE) ----------
def propublica():
    out = []
    for page in range(0, 30):  # ~750 env nonprofits
        try:
            d = json.loads(get(f"https://projects.propublica.org/nonprofits/api/v2/search.json?q=environmental&page={page}"))
            for o in d.get("organizations", []):
                rev = o.get("income_amount") or o.get("revenue_amount") or 0
                out.append(row("propublica-990", o["name"], "US nonprofit (990)",
                    raised=rev, website=f"https://projects.propublica.org/nonprofits/organizations/{o['ein']}",
                    notes=f"EIN {o['ein']} {o.get('city','')},{o.get('state','')} NTEE:{o.get('ntee_code','')} income:${rev:,}"))
            time.sleep(0.4)
        except Exception as e:
            print("propublica", page, e); break
    insert(out); print("propublica:", len(out))

# ---------- ReliefWeb: jobs (tech-need) + sources (orgs) ----------
def reliefweb():
    # jobs mentioning tech roles -> hiring org = budget + tech gap
    out = []
    try:
        d = json.loads(get("https://api.reliefweb.int/v2/jobs?appname=defi4refi&limit=200&profile=list&query[value]=developer+OR+data+OR+gis+OR+digital+OR+software&fields[include][]=source.name&fields[include][]=title&fields[include][]=date.created&fields[include][]=url"))
        for j in d.get("data", []):
            f = j.get("fields", {})
            src = (f.get("source") or [{}])[0].get("name", "?")
            title = f.get("title", "")
            if TECH.search(title):
                out.append(row("reliefweb-jobs", src, "NGO hiring tech (tech-need signal)",
                    website=f.get("url", ""), notes=f"hiring: {title} posted {(f.get('date') or {}).get('created','')[:10]}"))
        insert(out); print("reliefweb jobs:", len(out))
    except Exception as e:
        print("reliefweb jobs:", e)
    # sources = orgs
    out = []
    try:
        for off in range(0, 2000, 200):
            d = json.loads(get(f"https://api.reliefweb.int/v2/sources?appname=defi4refi&limit=200&offset={off}&fields[include][]=name&fields[include][]=homepage&fields[include][]=type.name&fields[include][]=country.name"))
            for s in d.get("data", []):
                f = s.get("fields", {})
                ctry = ",".join(c.get("name","") for c in (f.get("country") or []))
                out.append(row("reliefweb-source", f.get("name","?"), "NGO/agency (ReliefWeb source)",
                    website=f.get("homepage",""), notes=f"type:{(f.get('type') or {}).get('name','')} region:{ctry}"))
            if len(d.get("data",[])) < 200: break
            time.sleep(0.3)
        insert(out); print("reliefweb sources:", len(out))
    except Exception as e:
        print("reliefweb sources:", e)

# ---------- World Bank projects (implementing orgs + amounts) ----------
def worldbank():
    out = []
    try:
        for off in range(0, 2000, 100):
            d = json.loads(get(f"https://search.worldbank.org/api/v3/projects?format=json&rows=100&os={off}&qterm=climate+conservation&fl=proj_id,project_name,countryshortname,totalamt,boardapprovaldate,impagency"))
            for pid, p in (d.get("projects") or {}).items():
                if not isinstance(p, dict):
                    continue
                amt = p.get("totalamt") or p.get("curr_total_commitment") or 0
                out.append(row("worldbank", p.get("project_name","?")[:120], "World Bank project",
                    raised=float(amt) if str(amt).replace(".","").isdigit() else 0,
                    website=f"https://projects.worldbank.org/en/projects-operations/project-detail/{p.get('proj_id','')}",
                    notes=f"{p.get('countryshortname','')} approved:{p.get('boardapprovaldate','')[:10]}"))
            if len(d.get("projects") or {}) < 90: break
            time.sleep(0.3)
        insert(out); print("worldbank:", len(out))
    except Exception as e:
        print("worldbank:", e)

# ---------- Open Collective (collectives w/ public budgets) ----------
def opencollective():
    out = []
    qg = '{ accounts(limit:50, offset:%d, searchTerm:"climate") { nodes { name slug website stats { totalNetAmountReceived { value currency } } } } }'
    try:
        for off in range(0, 500, 50):
            d = json.loads(get("https://api.opencollective.com/graphql/v2",
                data=json.dumps({"query": qg % off}).encode(),
                headers={"Content-Type": "application/json"}))
            for a in d["data"]["accounts"]["nodes"]:
                rec = ((a.get("stats") or {}).get("totalNetAmountReceived") or {}).get("value") or 0
                out.append(row("opencollective", a["name"], "open collective",
                    raised=float(rec), website=a.get("website") or f"https://opencollective.com/{a['slug']}",
                    notes=f"raised ${rec:,.0f} via OC"))
            time.sleep(0.5)
        insert(out); print("opencollective:", len(out))
    except Exception as e:
        print("opencollective:", e)

# ---------- grants.gov search ----------
def grantsgov():
    out = []
    try:
        body = {"keyword": "environmental OR climate OR conservation", "oppStatuses": "forecasted|posted", "rows": 500}
        d = json.loads(get("https://api.grants.gov/v1/api/search2",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))
        for g in (d.get("data") or {}).get("oppHits", []):
            out.append(row("grants-gov", g.get("title","?")[:120], "US federal opportunity",
                website=f"https://grants.gov/search-results-detail/{g.get('id','')}",
                notes=f"agency:{g.get('agency','')} close:{g.get('closeDate','')[:10]} open:{g.get('openDate','')[:10]}"))
        insert(out); print("grants.gov:", len(out))
    except Exception as e:
        print("grants.gov:", e)

import sys
fns = {"propublica":propublica,"reliefweb":reliefweb,"worldbank":worldbank,"opencollective":opencollective,"grantsgov":grantsgov}
for fn in [fns[a] for a in sys.argv[1:]] or fns.values():
    try:
        fn()
    except Exception as e:
        print(fn.__name__, "FATAL", e)
print("ALL DONE")
