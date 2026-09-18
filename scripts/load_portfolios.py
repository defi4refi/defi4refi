#!/usr/bin/env python3
"""VC portfolio + accelerator cohort scrapers -> raw_leads. Light HTML parse, no JS."""
import json, re, time, urllib.request, urllib.parse

CH = "http://localhost:8123/"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def insert(rows):
    if rows:
        q("INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")

# portfolio pages: scrape linked org names/domains from portfolio/company grids
PAGES = {
    "lowercarbon": "https://lowercarbon.com/portfolio",
    "paleblue": "https://paleblue.vc/portfolio",
    "congruent": "https://congruentvc.com/portfolio/",
    "climatecapital": "https://www.climatecapital.co/portfolio",
    "mcj": "https://www.mcj.vc/portfolio",
    "breakthrough": "https://www.breakthroughenergy.org/our-work/portfolio-companies/",
    "elemental": "https://elementalexcelerator.com/portfolio/",
    "sosv-climate": "https://sosv.com/climate/",
}

for tag, url in PAGES.items():
    try:
        h = get(url)
        # external links = portfolio companies; filter nav/social/footer junk
        links = re.findall(r'href="(https?://[^"]+)"', h)
        junk = re.compile(r"(lowercarbon|paleblue|congruent|climatecapital|mcj|breakthrough|elemental|sosv|twitter|linkedin|facebook|instagram|youtube|mailto|javascript|#|wp-content|fonts\.)", re.I)
        cands = []
        for l in links:
            dom = urllib.parse.urlparse(l).netloc.lower().replace("www.", "")
            if not dom or junk.search(l):
                continue
            name = dom.split(".")[0].replace("-", " ").title()
            cands.append({"source": "vc-portfolio-" + tag, "name": name,
                          "category": "VC portfolio company (climate)", "raised_usd": 0,
                          "website": l.split("?")[0], "chain": "", "notes": f"via {tag}", "priority": "vc-backed"})
        # dedup by domain
        seen = set(); uniq = []
        for c in cands:
            d = urllib.parse.urlparse(c["website"]).netloc
            if d not in seen:
                seen.add(d); uniq.append(c)
        insert(uniq)
        print(tag, len(uniq))
        time.sleep(0.5)
    except Exception as e:
        print(tag, "ERR", str(e)[:100])
print("DONE")
