#!/usr/bin/env python3
"""Env-filtered global loaders -> raw_leads: NIH RePORTER, NSF awards, World Bank extra,
IDB env projects, IUCN members. Env filter applied AT LOAD."""
import json, re, time, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"
ENV = re.compile(r"environ|conserv|climat|forest|reforest|ocean|water|solar|renewab|green|sustain|biodiv|wildlife|nature|agro|ecolog|carbon|marine|habitat|wetland|reef|pollution|restoration|fisheries|land use|emission", re.I)
ENV_TERMS = ["climate change", "conservation", "renewable energy", "biodiversity", "reforestation",
             "ocean conservation", "water quality", "sustainable agriculture", "carbon emissions",
             "environmental protection", "wildlife", "ecosystem restoration", "pollution",
             "marine conservation", "agroecology"]

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def insert(rows):
    if rows:
        q("INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def row(source, name, category="", raised=0.0, website="", chain="", notes="", priority="env"):
    return {"source": source, "name": name, "category": category, "raised_usd": float(raised or 0),
            "website": website, "chain": chain, "notes": notes[:900], "priority": priority}

def get(url, data=None, headers=None, timeout=40):
    req = urllib.request.Request(url, data=data,
        headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")

# ---------- NIH RePORTER: env-health/ecology projects ----------
def nih():
    out = []
    for term in ENV_TERMS:
        for offset in range(0, 2000, 500):
            body = {"criteria": {"advanced_text_search": {"operator": "and",
                                 "search_field": "projecttitle,abstracttext,terms",
                                 "search_text": term}},
                    "limit": 500, "offset": offset,
                    "include_fields": ["Organization", "AwardAmount", "FiscalYear", "ProjectTitle", "Country"]}
            try:
                d = json.loads(get("https://api.reporter.nih.gov/v2/projects/search",
                                   data=json.dumps(body).encode()))
            except Exception as e:
                print("nih", term, offset, str(e)[:80]); break
            res = d.get("results") or []
            for p in res:
                org = (p.get("organization") or {}).get("org_name") or ""
                if not org: continue
                amt = p.get("award_amount") or 0
                out.append(row("nih-reporter", org.title(), "NIH env-health grantee",
                    raised=amt, website="https://reporter.nih.gov",
                    notes=f"NIH ${amt:,.0f} FY{p.get('fiscal_year','')} {str(p.get('project_title',''))[:120]} {(p.get('organization') or {}).get('org_country','')}"))
            if len(res) < 500: break
            time.sleep(0.4)
        if len(out) >= 4000:
            insert(out); out = []
        print("nih:", term, "done")
    insert(out); print("nih DONE")

# ---------- NSF awards: env keywords ----------
def nsf():
    out = []
    for term in ENV_TERMS:
        off = 1
        while off < 10000:
            try:
                d = json.loads(get(f"https://www.research.gov/awardapi-service/v1/awards.json?keyword={urllib.parse.quote(term)}&offset={off}&rpp=25&printFields=id,title,fundsObligatedAmt,awardeeName,startDate"))
            except Exception as e:
                print("nsf", term, off, str(e)[:80]); break
            awards = d["response"].get("award") or []
            if not awards: break
            for a in awards:
                amt = float(a.get("fundsObligatedAmt") or 0)
                out.append(row("nsf", (a.get("awardeeName") or "?").title(), "NSF grantee",
                    raised=amt, website=f"https://www.nsf.gov/awardsearch/show-award?AWD_ID={a.get('id','')}",
                    notes=f"NSF ${amt:,.0f} {str(a.get('title',''))[:120]} start:{a.get('startDate','')}"))
            off += 25
            time.sleep(0.35)
        if len(out) >= 4000:
            insert(out); out = []
        print("nsf:", term, "done")
    insert(out); print("nsf DONE")

# ---------- World Bank extra env terms ----------
def worldbank_extra():
    out = []
    for term in ["biodiversity", "renewable energy", "water management", "reforestation", "sustainable agriculture", "marine conservation"]:
        for off in range(0, 1500, 100):
            try:
                d = json.loads(get(f"https://search.worldbank.org/api/v3/projects?format=json&rows=100&os={off}&qterm={urllib.parse.quote(term)}&fl=proj_id,project_name,countryshortname,totalamt,boardapprovaldate,impagency"))
            except Exception as e:
                print("wb", term, off, str(e)[:80]); break
            projs = d.get("projects") or {}
            for pid, p in projs.items():
                if not isinstance(p, dict): continue
                amt = p.get("totalamt") or 0
                out.append(row("worldbank", p.get("project_name","?")[:120], "World Bank env project",
                    raised=float(amt) if str(amt).replace(".","").isdigit() else 0,
                    website=f"https://projects.worldbank.org/en/projects-operations/project-detail/{p.get('proj_id','')}",
                    notes=f"{p.get('countryshortname','')} approved:{str(p.get('boardapprovaldate',''))[:10]} impl:{p.get('impagency','')}"))
            if len(projs) < 90: break
            time.sleep(0.3)
        print("wb:", term)
    insert(out); print("wb DONE")

# ---------- IDB projects ----------
def idb():
    try:
        # IDB open data API — projects endpoint
        out = []
        for off in range(0, 3000, 100):
            d = json.loads(get(f"https://www.iadb.org/api/projects?limit=100&offset={off}&query=environment+climate"))
            items = d.get("items") or d.get("projects") or []
            for p in items:
                amt = p.get("totalCost") or p.get("amount") or 0
                out.append(row("idb", p.get("projectName") or p.get("title","?"), "IDB env project",
                    raised=float(amt) if str(amt).replace(".","").isdigit() else 0,
                    website=p.get("url",""), notes=str(p.get("country",""))[:100]))
            if len(items) < 100: break
            time.sleep(0.4)
        insert(out); print("idb:", len(out))
    except Exception as e:
        print("idb", str(e)[:120])

# ---------- IUCN members ----------
def iucn():
    try:
        h = get("https://iucn.org/about/members/iucn-members-list")
        # member names in list markup
        names = set(re.findall(r'>([A-Z][A-Za-z .,&\'-]{8,80}(?:Foundation|Trust|Society|Institute|Conservation|Association|Centre|Center|Council|Network|Alliance|Union|Federation|Program|Programme|Fund|Initiative|Coalition|Forum|Group|Commission|Ministry|University|Academy|Department|Agency|Authority|Organization|Organisation|NGO|Charity|Coalition|Service|Bureau|Office|Institute|College|School|Park|Reserve|Sanctuary|Center))<', h))
        out = [row("iucn", n.strip(), "IUCN member (env NGO)", website="https://iucn.org",
                   notes="IUCN member list") for n in names]
        insert(out); print("iucn:", len(out))
    except Exception as e:
        print("iucn", str(e)[:120])

fns = {"nih": nih, "nsf": nsf, "worldbank": worldbank_extra, "idb": idb, "iucn": iucn}
for a in (sys.argv[1:] or fns):
    try:
        fns[a]()
    except Exception as e:
        print(a, "FATAL", str(e)[:150])
print("ALL DONE")
