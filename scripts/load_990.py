#!/usr/bin/env python3
"""IRS 990 e-file: index CSV -> env-name filter -> per-filing XML -> revenue+website+officers."""
import csv, io, json, re, sys, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

CH = "http://localhost:8123/"
UA = {"User-Agent": "defi4refi/1.0 (research)"}
ENV = re.compile(r"(?i)conserv|environ|wildlife|climat|forest|park|nature|river|watershed|"
                 r"ecolog|bird|marine|ocean|animal|habitat|land trust|trail|garden|"
                 r"sustainab|renewab|solar|energy eff|recycl|pollut|air qual|water qual|"
                 r"earth|planet|biodiv|wetland|prairie|mountain|sierra|appalach|cascad|"
                 r"arbor|tree|botanic|garden|farm|food bank|organic|regenerat")

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def ins(table, rows):
    if rows:
        q(f"INSERT INTO defi4refi.{table} FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def get(url, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)
    return r.read() if raw else r.read().decode("utf-8", "replace")

NS = "{http://www.irs.gov/efile}"
def xtext(root, *path):
    for tag in path:
        e = root.find(".//" + NS + tag) or root.find(".//" + tag)
        if e is not None and e.text:
            return e.text.strip()
    return ""

def parse_filing(object_id, ein, name, year_dir):
    url = f"https://apps.irs.gov/pub/epostcard/990/xml/{year_dir}/{object_id}_public.xml"
    try:
        xml = get(url)
        root = ET.fromstring(xml)
        rev = xtext(root, "CYTotalRevenueAmt", "TotalRevenueCurrentYear", "RevenueAmt")
        rev = float(re.sub(r"[^0-9.]", "", rev)) if rev else 0
        site = xtext(root, "WebsiteAddressTxt", "WebSite")
        officers = []
        for grp in root.findall(".//" + NS + "Form990PartVIISectionAGrp") + root.findall(".//Form990PartVIISectionAGrp"):
            nm = xtext(grp, "PersonNm")
            ti = xtext(grp, "TitleTxt")
            if nm:
                officers.append((nm.title(), ti.title()))
        lead = {"name": name.title(), "source": "irs-990", "notes": f"EIN {ein} e-filed 990",
                "website": (site if site.startswith("http") else ("https://"+site if site else "")),
                "priority": "ein:" + ein, "raised_usd": rev, "chain": "", "github": "", "twitter": "", "topics": ""}
        contacts = [{"channel": "person", "value": f"{n}|{t}", "verified": 0, "source": "990-officer"} for n, t in officers[:8]]
        if site:
            contacts.append({"channel": "website", "value": lead["website"], "verified": 0, "source": "990-xml"})
        return lead, contacts
    except Exception:
        return None, []

def run(year=2024, maxfilings=6000):
    print(f"downloading index_{year}.csv …", flush=True)
    raw = get(f"https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv")
    rows = list(csv.DictReader(io.StringIO(raw)))
    env = [r for r in rows if ENV.search(r.get("TAXPAYER_NAME") or "")][:maxfilings]
    print(f"{len(rows)} filings → {len(env)} env-name matches", flush=True)
    total_leads, total_contacts = [], []
    with ThreadPoolExecutor(16) as ex:
        futs = [ex.submit(parse_filing, r["OBJECT_ID"], r["EIN"], r["TAXPAYER_NAME"], str(year)) for r in env]
        for i, f in enumerate(futs):
            lead, cts = f.result()
            if lead:
                total_leads.append(lead)
                for c in cts:
                    c["org_id"] = None  # resolved later — store ein in source for now
                total_contacts.extend(cts)
            if (i + 1) % 500 == 0:
                print(i + 1, "filings →", len(total_leads), "leads,", len(total_contacts), "contacts", flush=True)
                ins("raw_leads", total_leads); total_leads = []
    ins("raw_leads", total_leads)
    print("990 DONE:", len(env), "filings scanned")

if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 2024, int(sys.argv[2]) if len(sys.argv) > 2 else 6000)
