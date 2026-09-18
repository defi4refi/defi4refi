#!/usr/bin/env python3
"""Queue governor: keep outreach_queue depth >= 3x weekly batch. Escalates discovery if low."""
import json, os, subprocess, sys, urllib.request, urllib.parse

CH = "http://localhost:8123/"
WEEKLY_BATCH = int(os.environ.get("WEEKLY_BATCH", "100"))
MIN_DEPTH = 3 * WEEKLY_BATCH

def q(sql):
    return urllib.request.urlopen("http://localhost:8123/?query=" + urllib.parse.quote(sql)).read().decode()

depth = int(q("SELECT count() FROM defi4refi.outreach_queue"))
total_orgs = int(q("SELECT count() FROM defi4refi.orgs FINAL"))
funded = int(q("SELECT uniq(org_id) FROM defi4refi.funding_events WHERE amount_usd>0 AND program!='token-market-cap'"))
print(f"queue depth: {depth} (min {MIN_DEPTH}) | orgs: {total_orgs} | funded-known: {funded}")

if depth >= MIN_DEPTH:
    print("OK — queue healthy"); sys.exit(0)

# escalation ladder
escalations = [
    ("lower score threshold", "outreach_queue threshold 35→30 — edit score gate in outreach_queue.sql"),
    ("resume pagination", "python3 scripts/load_scale.py — deeper pages"),
    ("next bulk source", "load next registry: UK CC bulk, CORDIS, CRA, NGO Darpan"),
    ("widen regions", "pull more non-US registries"),
]
for i, (name, action) in enumerate(escalations):
    print(f"ESCALATION {i+1}: {name} — {action}")

q("""INSERT INTO defi4refi.signals FORMAT JSONEachRow""".replace("INSERT INTO defi4refi.signals FORMAT JSONEachRow", ""), ) if False else None
urllib.request.urlopen(urllib.request.Request(
    "http://localhost:8123/?query=" + urllib.parse.quote(
        "INSERT INTO defi4refi.signals (org_id, signal_type, detail) VALUES ('', 'queue_low', 'queue depth %d below min %d')" % (depth, MIN_DEPTH)),
    data=b"", method="POST"))
print("logged queue_low signal")
