#!/usr/bin/env python3
"""Bulk-file loaders: ACNC (AU), Brønnøysund (NO). CSV/API -> raw_leads."""
import csv, json, time, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def insert(rows):
    if rows:
        q("INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

# ---------- ACNC ----------
def acnc():
    out = []
    for r in csv.DictReader(open("/tmp/acnc.csv")):
        if r.get("Advancing_natual_environment") != "Y" and r.get("environment") != "Y":
            continue
        size = r.get("Charity_Size", "")
        out.append({"source": "acnc-au", "name": r["Charity_Legal_Name"].strip(),
            "category": f"AU charity ({size})", "raised_usd": 0,
            "website": r.get("Charity_Website") or "", "chain": "",
            "notes": f"ABN {r.get('ABN','')} {r.get('Town_City','')},{r.get('State','')} est:{r.get('Date_Organisation_Established','')} size:{size}",
            "priority": "env"})
        if len(out) >= 2000 and not out[-1].get("_"):
            pass
    # batch insert in chunks of 2000
    for i in range(0, len(out), 2000):
        insert(out[i:i+2000])
    print("acnc:", len(out))

# ---------- Brønnøysund (Norway entities, env-ish naeringskoder) ----------
def brreg():
    # naeringskode 35.1x = electricity; 01-03 agri/forest/fish; 38 waste; 39 remediation
    codes = ["39.000", "35.110", "02.400", "38.220", "01.610", "03.220"]
    out = []
    for code in codes:
        try:
            for page in range(0, 3):
                d = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f"https://data.brreg.no/enhetsregisteret/api/enheter?naeringskode={code}&size=100&page={page}",
                    headers={"User-Agent": "defi4refi/1.0"}), timeout=20).read())
                ents = (d.get("_embedded") or {}).get("enheter") or []
                for e in ents:
                    out.append({"source": "brreg-no", "name": e.get("navn", "?"),
                        "category": f"NO entity (nace {code})", "raised_usd": 0,
                        "website": (e.get("hjemmeside") or ""), "chain": "",
                        "notes": f"orgform:{e.get('organisasjonsform',{}).get('kode','')} reg:{e.get('registreringsdatoEnhetsregisteret','')}",
                        "priority": "env"})
                if len(ents) < 100:
                    break
                time.sleep(0.3)
        except Exception as ex:
            print("brreg", code, ex)
    insert(out); print("brreg:", len(out))

fns = {"acnc": acnc, "brreg": brreg}
for a in (sys.argv[1:] or fns):
    fns[a]()
print("DONE")
