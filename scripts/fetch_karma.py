#!/usr/bin/env python3
"""Paginate Karma GAP API; sparse pages tolerated (stop after 40 consecutive empty)."""
import json, time, urllib.request

OUT = "/tmp/karma_projects.jsonl"
seen = set()
total = 0
empties = 0
with open(OUT, "w") as f:
    for page in range(1, 800):
        d = []
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"https://gapapi.karmahq.xyz/projects?page={page}",
                    headers={"User-Agent": "defi4refi-leads/1.0"})
                d = json.load(urllib.request.urlopen(req, timeout=30))
                break
            except Exception:
                time.sleep(2 * attempt + 1)
        if not d:
            empties += 1
            if empties >= 40:
                print(f"40 consecutive empties at page {page} — done. total={total}", flush=True)
                break
        else:
            empties = 0
            for p in d:
                uid = p.get("uid")
                if uid and uid not in seen:
                    seen.add(uid)
                    f.write(json.dumps(p) + "\n")
                    total += 1
        if page % 50 == 0:
            print(f"page {page}: {total} projects ({empties} consecutive empties)", flush=True)
        time.sleep(0.2)
print(f"DONE total={total}", flush=True)
