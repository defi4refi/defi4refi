#!/usr/bin/env python3
"""LLM relevance pass: top-N orgs -> structured regen/dev-need scores -> llm_scores."""
import json, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "llama3.1-8b-tools-32k"
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 300

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

q("""CREATE TABLE IF NOT EXISTS defi4refi.llm_scores (
  org_id String, regen_fit Float32, dev_need Float32, disposable_estimate Float32,
  reason String, scored_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY org_id""")

orgs = rows_json(f"""
  SELECT v.`org_id` AS org_id, v.canonical_name, v.funding_usd, v.sources, v.score,
         groupArray(substring(r.notes,1,300)) AS notes
  FROM defi4refi.v_scored v
  LEFT JOIN defi4refi.lead_org_map m ON m.org_id = v.`org_id`
  LEFT JOIN defi4refi.raw_leads r ON r.name = m.name AND r.source = m.source
  GROUP BY ALL ORDER BY v.score DESC LIMIT {TOP_N}
""")
print("scoring", len(orgs), "orgs with", MODEL)

PROMPT = """Score this org for a ReFi/regenerative dev studio. JSON only, no prose.
Org: {name}
Sources: {sources}
Known funding USD: {funding}
Notes: {notes}
Return exactly: {{"regen_fit": 0-1, "dev_need": 0-1, "disposable": 0-1, "reason": "<15 words"}}
regen_fit = environmental/regenerative alignment. dev_need = needs technical help (not already a tech co). disposable = likely has spendable funds for dev work."""

done = 0
for o in orgs:
    prompt = PROMPT.format(name=o["canonical_name"][:80], sources=o["sources"],
                           funding=o.get("funding_usd") or 0, notes=" | ".join(o["notes"])[:600])
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps({
            "model": MODEL, "prompt": prompt, "stream": False, "format": "json",
            "options": {"temperature": 0.1, "num_predict": 80}}).encode())
        resp = json.load(urllib.request.urlopen(req, timeout=60))
        j = json.loads(resp.get("response") or "{}")
        q("INSERT INTO defi4refi.llm_scores FORMAT JSONEachRow", data=json.dumps({
            "org_id": o["org_id"], "regen_fit": float(j.get("regen_fit", 0)),
            "dev_need": float(j.get("dev_need", 0)), "disposable_estimate": float(j.get("disposable", 0)),
            "reason": str(j.get("reason", ""))[:200]}))
        done += 1
        if done % 25 == 0:
            print(f"{done}/{len(orgs)}", flush=True)
    except Exception as e:
        print("llm err:", str(e)[:120], flush=True)
print("LLM DONE", done)
