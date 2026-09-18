#!/usr/bin/env python3
"""Named-person contacts: ProPublica 990 officers + NIH PIs, for funded orgs lacking person channel."""
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

# ---- ProPublica: org detail -> officers (name + title) ----
def propub_persons():
    # funded propub orgs keyed by EIN in website field
    orgs = rows_json("""
      SELECT DISTINCT m.org_id, extract(l.website, 'organizations/(\\d+)') AS ein
      FROM defi4refi.lead_org_map m
      JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source
      WHERE m.source='propublica-990' AND ein != ''
        AND m.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='person' AND source='990-officer')
      LIMIT 5000""")
    print("propub orgs:", len(orgs), flush=True)
    out = []
    for i, o in enumerate(orgs):
        try:
            d = getj(f"https://projects.propublica.org/nonprofits/api/v2/organizations/{o['ein']}.json")
            org = d.get("organization") or {}
            for f in (d.get("filings_with_data") or [])[:1]:
                pass
            # officers live in filings_with_data[].pdf? -> officer names in 'organization.officers' newer API
            for off in (org.get("officers") or []):
                nm, ti = (off.get("name") or "").strip().title(), (off.get("title") or "").strip().title()
                if nm and len(nm) > 4:
                    out.append({"org_id": o["org_id"], "channel": "person", "value": f"{nm}|{ti}", "verified": 0, "source": "990-officer"})
            if not out or True:
                # fallback: filings carry officer info in 'pdf_url' metadata? use data_source_url fields
                pass
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print("propub", i + 1, "→", len(out), "officers", flush=True)
            ins(out); out = []
        time.sleep(0.25)
    ins(out)
    print("propub persons done:", len(out))

# ---- NIH PI names for funded orgs w/o person ----
def nih_persons():
    orgs = rows_json("""
      SELECT DISTINCT m.org_id, m.name FROM defi4refi.lead_org_map m
      WHERE m.source='nih-reporter'
        AND m.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='person' AND source='nih-pi')
      LIMIT 2000""")
    print("nih orgs:", len(orgs), flush=True)
    out = []
    for i, o in enumerate(orgs):
        try:
            body = json.dumps({"criteria": {"org_names": [o["name"].upper()]}, "limit": 3,
                               "include_fields": ["ContactPiName", "ProjectTitle", "AwardAmount"]}).encode()
            d = getj("https://api.reporter.nih.gov/v2/projects/search")
            # need POST
        except Exception:
            pass
    # POST version
    for i, o in enumerate(orgs):
        try:
            body = json.dumps({"criteria": {"org_names": [o["name"].upper()]}, "limit": 3,
                               "include_fields": ["ContactPiName", "ProjectTitle"]}).encode()
            r = urllib.request.urlopen(urllib.request.Request(
                "https://api.reporter.nih.gov/v2/projects/search", data=body,
                headers={"Content-Type": "application/json"}), timeout=15)
            d = json.loads(r.read())
            for p in (d.get("results") or []):
                pi = (p.get("contact_pi_name") or "").strip()
                if pi:
                    out.append({"org_id": o["org_id"], "channel": "person", "value": pi.title() + "|Principal Investigator", "verified": 0, "source": "nih-pi"})
                    break
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print("nih", i + 1, "→", len(out), "PIs", flush=True)
            ins(out); out = []
        time.sleep(0.3)
    ins(out)
    print("nih persons done:", len(out))

# ---- NSF awards: PI + coPI emails + awardee phone for funded orgs ----
def nsf_persons():
    orgs = rows_json("""
      SELECT DISTINCT m.org_id, m.name FROM defi4refi.lead_org_map m
      WHERE m.source='nsf'
        AND m.org_id NOT IN (SELECT org_id FROM defi4refi.contacts WHERE channel='person' AND source='nsf-pi')
      LIMIT 3000""")
    print("nsf orgs:", len(orgs), flush=True)
    out = []
    for i, o in enumerate(orgs):
        try:
            d = getj("https://api.nsf.gov/services/v1/awards.json?awardeeName=" +
                     urllib.parse.quote(o["name"][:60]) + "&rpp=3")
            for a in (d.get("response", {}).get("award") or [])[:3]:
                oid = o["org_id"]
                pi = " ".join(filter(None, [a.get("piFirstName"), a.get("piLastName")])).strip()
                if pi:
                    out.append({"org_id": oid, "channel": "person", "value": pi + "|PI", "verified": 0, "source": "nsf-pi"})
                for copi in (a.get("coPDPI") or []):
                    m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", copi)
                    nm = re.sub(r"[a-zA-Z0-9._%+-]+@\S+", "", copi).strip()
                    if m:
                        out.append({"org_id": oid, "channel": "email", "value": m.group(1).lower(), "verified": 0, "source": "nsf-copi"})
                        if nm:
                            out.append({"org_id": oid, "channel": "person", "value": nm + "|co-PI", "verified": 0, "source": "nsf-copi"})
                if a.get("awardeePhone"):
                    out.append({"org_id": oid, "channel": "phone", "value": a["awardeePhone"], "verified": 0, "source": "nsf-award"})
                if out:
                    break
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print("nsf", i + 1, "→", len(out), "contacts", flush=True)
            ins(out); out = []
        time.sleep(0.3)
    ins(out)
    print("nsf persons done:", len(out))

if __name__ == "__main__":
    {"nih": nih_persons, "nsf": nsf_persons}[sys.argv[1]]() if len(sys.argv) > 1 else propub_persons()
