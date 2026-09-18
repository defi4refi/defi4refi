#!/usr/bin/env python3
"""Outreach agent: pick best Tier-A channel per org -> LLM-drafted open line -> drafts table.
Reply triage: classify inbound -> route. Runs locally via laptop Ollama."""
import json, urllib.request, urllib.parse, sys

CH = "http://localhost:8123/"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "llama3.1-8b-tools-32k"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def llm(prompt, fmt_json=True, n=120):
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps({
            "model": MODEL, "prompt": prompt, "stream": False,
            "format": "json" if fmt_json else None,
            "options": {"temperature": 0.3, "num_predict": n}}).encode())
        return json.loads(urllib.request.urlopen(req, timeout=90).read().decode()).get("response", "")
    except Exception as e:
        return ""

# channel priority for outreach: agent-autonomous first
CHANNEL_PRIORITY = ["bluesky", "mastodon", "nostr", "farcaster", "matrix", "github",
                    "email", "telegram", "discord", "form", "substack", "twitter"]
CH_PATH = {"bluesky": "DM/post-mention on Bluesky", "mastodon": "mention/DM on fediverse",
           "nostr": "nostr DM", "farcaster": "warpcast reply", "matrix": "matrix DM",
           "github": "open issue on their repo", "email": "email",
           "telegram": "telegram DM", "discord": "discord", "form": "fill contact form",
           "substack": "comment on substack", "twitter": "twitter (read-only seed)"}

def pick_channel(contacts):
    for ch in CHANNEL_PRIORITY:
        for c in contacts:
            if c["channel"] == ch:
                return ch, c["value"]
    return None, None

# ---------- 1. draft outreach for top queue orgs ----------
def draft(top_n=40):
    orgs = rows_json(f"""
      SELECT v.`org_id` AS org_id, v.canonical_name, v.funding_usd, v.days_since_funded,
             v.sources, l.reason AS llm_reason
      FROM defi4refi.v_scored v
      LEFT JOIN defi4refi.llm_scores l ON l.org_id = v.`org_id`
      WHERE v.`org_id` IN (SELECT org_id FROM defi4refi.contacts
                           WHERE channel IN ('bluesky','mastodon','nostr','farcaster','matrix','github','email','form'))
        AND v.`org_id` NOT IN (SELECT org_id FROM defi4refi.outreach_log)
        AND v.`org_id` NOT IN (SELECT org_id FROM defi4refi.drafts)
      ORDER BY v.score DESC LIMIT {top_n}""")
    print("drafting for", len(orgs), "orgs")
    for o in orgs:
        contacts = rows_json(f"SELECT channel, value FROM defi4refi.contacts WHERE org_id='{o['org_id']}'")
        ch, val = pick_channel(contacts)
        if not ch:
            continue
        prompt = f"""You are dev services studio 'defi4refi' reaching out. Write ONE personalized opening line (under 30 words) mentioning their recent funding. Then a 2-sentence pitch offering dev help (sliding scale / pay-what-you-feel). Return JSON: {{"open_line": "...", "body": "..."}}
Org: {o['canonical_name']}
Funding: ${o['funding_usd']:,.0f} received ~{o['days_since_funded']} days ago
Context: {(o.get('llm_reason') or '')[:150]}
Sources: {o['sources']}
Channel: {CH_PATH.get(ch, ch)}"""
        resp = llm(prompt)
        try:
            j = json.loads(resp)
            open_line = str(j.get("open_line", ""))[:300]
            body = str(j.get("body", ""))[:600]
        except Exception:
            open_line, body = "", ""
        q("INSERT INTO defi4refi.drafts FORMAT JSONEachRow", data=json.dumps({
            "org_id": o["org_id"], "channel": ch, "contact": val,
            "open_line": open_line, "body": body}))
    print("drafted")

# ---------- 2. reply triage ----------
def triage():
    pending = rows_json("SELECT org_id, body FROM defi4refi.replies WHERE reply_class=''")
    for r in pending:
        prompt = f"""Classify this outreach reply into exactly one: interested | question | not_now | negative | wrong_person. JSON: {{"class":"...","conf":0-1}}
Reply: {r['body'][:800]}"""
        resp = llm(prompt)
        try:
            j = json.loads(resp); cls, conf = str(j.get("class","")), float(j.get("conf",0.5))
        except Exception:
            cls, conf = "unknown", 0
        if cls:
            q(f"ALTER TABLE defi4refi.replies UPDATE reply_class='{cls}', reply_conf={conf} WHERE org_id='{r['org_id']}' AND reply_class=''")
    print("triaged", len(pending))

for a in (sys.argv[1:] or ["draft"]):
    {"draft": draft, "triage": triage}[a]()
print("AGENT DONE")
