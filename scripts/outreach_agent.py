#!/usr/bin/env python3
"""
Outreach agent with self-improvement loop.

Phases:
  1. draft   - LLM-drafted open lines + bodies, A/B variants, dynamic channel priority
  2. triage  - classify inbound replies
  3. learn   - compute per-channel/template/org metrics, auto-suppress dead channels,
              boost score for orgs that get replies, update channel_perf table
  4. report  - print current learning state

Infrastructure:
  ClickHouse (localhost:8123) — defi4refi schema
  Ollama   (localhost:11434)  — llama3.1-8b-tools-32k
"""
import json, os, sys, urllib.request, urllib.parse, hashlib

CH = os.environ.get("CH_URL", "http://localhost:8123/")
# LLM_PROVIDER: "ollama" (default, /api/generate) or "openai" (OpenAI-compatible
# /v1/chat/completions — e.g. freelm-gateway http://127.0.0.1:8081/v1 on the VPS)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434")
MODEL = os.environ.get("LLM_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1-8b-tools-32k"))

# ---- channel priority: empirical > hardcoded fallback ----
# At rest, channel_perf table holds empirical rates. On first run (empty table),
# fall back to hardcoded order. After learn() runs, the order updates.
HARDCODED_PRIORITY = ["bluesky", "mastodon", "nostr", "farcaster", "matrix",
                      "github", "email", "telegram", "discord", "form", "substack", "twitter"]
CH_PATH = {"bluesky": "Bluesky DM/post-mention", "mastodon": "fediverse mention/DM",
           "nostr": "nostr DM", "farcaster": "warpcast reply", "matrix": "matrix DM",
           "github": "GitHub issue", "email": "email", "telegram": "telegram DM",
           "discord": "discord", "form": "contact form", "substack": "substack comment",
           "twitter": "twitter (read-only seed)"}

# ---- HTTP helpers ----
def ch_q(sql, data=None):
    return urllib.request.urlopen(
        urllib.request.Request(CH + "?query=" + urllib.parse.quote(sql),
                               data=(data.encode() if data else b""), method="POST")).read().decode()

def rows(sql):
    return [json.loads(l) for l in ch_q(sql + " FORMAT JSONEachRow").splitlines() if l.strip()]

# ---- schema: self-provisioning (repo convention — no separate migration file) ----
SCHEMA = """
CREATE TABLE IF NOT EXISTS defi4refi.outreach_log (
  org_id String, channel String, value String, sent_at DateTime DEFAULT now(),
  status String DEFAULT 'sent'
) ENGINE = MergeTree ORDER BY sent_at;
CREATE TABLE IF NOT EXISTS defi4refi.suppression (
  org_id String, reason String, added_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY org_id;
CREATE TABLE IF NOT EXISTS defi4refi.org_github (
  org_id String, gh_org String, public_repos UInt32, last_push String,
  fetched_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY org_id;
CREATE TABLE IF NOT EXISTS defi4refi.drafts (
  org_id String, channel String, contact String, open_line String, body String,
  approved UInt8 DEFAULT 0, created_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY (org_id, created_at);
CREATE TABLE IF NOT EXISTS defi4refi.replies (
  org_id String, channel String, value String, body String,
  reply_class String DEFAULT '', reply_conf Float32 DEFAULT 0,
  received_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY received_at;
CREATE TABLE IF NOT EXISTS defi4refi.org_outcomes (
  org_id String, first_contact DateTime DEFAULT now(), replied Bool DEFAULT 1,
  reply_class String DEFAULT '', days_to_reply Int32 DEFAULT 0,
  updated_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY org_id;
CREATE TABLE IF NOT EXISTS defi4refi.suppression_auto (
  org_id String, channel String, reason String,
  suppressed_at DateTime DEFAULT now(), suppress_count UInt32 DEFAULT 1
) ENGINE = MergeTree ORDER BY org_id;
CREATE TABLE IF NOT EXISTS defi4refi.draft_variant_log (
  org_id String, variant UInt8, open_line String, body String,
  selected Bool, replied UInt8 DEFAULT 0, sent_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY (org_id, variant);
"""

CHANNEL_PERF_VIEW = """
CREATE OR REPLACE VIEW defi4refi.channel_perf AS
SELECT ol.channel AS channel,
       countIf(ol.status = 'sent') AS sends,
       countDistinctIf(r.org_id, r.org_id != '' AND r.reply_class != '') AS replies,
       round(countDistinctIf(r.org_id, r.org_id != '' AND r.reply_class != '')
             / greatest(countIf(ol.status = 'sent'), 1), 3) AS reply_rate,
       min(ol.sent_at) AS first_sent, max(ol.sent_at) AS last_sent
FROM defi4refi.outreach_log ol
LEFT JOIN defi4refi.replies r ON r.org_id = ol.org_id
GROUP BY ol.channel
"""

def ensure_schema():
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            ch_q(stmt)
    try:
        ch_q(CHANNEL_PERF_VIEW)
    except Exception:
        pass  # needs v_scored-era tables; view optional on first boot

def ins(rows):
    if rows:
        ch_q("INSERT INTO defi4refi.drafts FORMAT JSONEachRow",
             data="\n".join(json.dumps(r) for r in rows))

def ins_cperf(rows):
    if rows:
        ch_q("INSERT INTO defi4refi.channel_perf FORMAT JSONEachRow",
             data="\n".join(json.dumps(r) for r in rows))

def ins_octo(rows):
    if rows:
        ch_q("INSERT INTO defi4refi.org_outcomes FORMAT JSONEachRow",
             data="\n".join(json.dumps(r) for r in rows))

def ins_supp(rows):
    if rows:
        ch_q("INSERT INTO defi4refi.suppression_auto FORMAT JSONEachRow",
             data="\n".join(json.dumps(r) for r in rows))

def ins_var(rows):
    if rows:
        ch_q("INSERT INTO defi4refi.draft_variant_log FORMAT JSONEachRow",
             data="\n".join(json.dumps(r) for r in rows))

# ---- LLM (ollama native or OpenAI-compatible) ----
def llm(prompt, fmt_json=True, n=120):
    try:
        if LLM_PROVIDER == "openai":
            req = urllib.request.Request(LLM_URL.rstrip("/") + "/chat/completions",
                data=json.dumps({"model": MODEL,
                                 "messages": [{"role": "user", "content": prompt}],
                                 "temperature": 0.25, "max_tokens": n}).encode(),
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
            return r["choices"][0]["message"]["content"]
        req = urllib.request.Request(LLM_URL.rstrip("/") + "/api/generate", data=json.dumps({
            "model": MODEL, "prompt": prompt, "stream": False,
            "format": "json" if fmt_json else None,
            "options": {"temperature": 0.25, "num_predict": n}}).encode())
        return json.loads(urllib.request.urlopen(req, timeout=90).read().decode()).get("response", "")
    except Exception as e:
        print(f"  [llm error: {e}]", file=sys.stderr)
        return ""

# ---- channel selection: empirical > hardcoded ----
def empirical_channels():
    """Return channels sorted by empirical reply_rate (desc), with sends >= 5.
    Falls back to HARDCODED_PRIORITY if no data."""
    cperf = rows("""SELECT channel, sends, replies,
        round(replies / greatest(sends,1), 3) AS rate
        FROM defi4refi.channel_perf
        ORDER BY sends DESC, rate DESC""")
    if not cperf:
        return HARDCODED_PRIORITY[:]
    proven = [c["channel"] for c in cperf if c["sends"] >= 5]
    if proven:
        return proven
    # mix: proven channels first, then hardcode the rest
    result = proven[:]
    for ch in HARDCODED_PRIORITY:
        if ch not in result:
            result.append(ch)
    return result

def pick_channel(contacts):
    """Pick best channel for an org given its contacts, using empirical priority."""
    channels = empirical_channels()
    for ch in channels:
        for c in contacts:
            if c["channel"] == ch:
                return ch, c["value"]
    return None, None

# ---- 1. DRAFT: A/B variants + dynamic channel priority ----
def draft(top_n=40):
    orgs = rows(f"""SELECT v.org_id, v.canonical_name, v.funding_usd, v.days_since_funded,
        v.sources, l.reason AS llm_reason
        FROM defi4refi.v_scored v
        LEFT JOIN defi4refi.llm_scores l ON l.org_id = v.org_id
        WHERE v.org_id IN (SELECT org_id FROM defi4refi.contacts
            WHERE channel IN ('bluesky','mastodon','nostr','farcaster','matrix',
                              'github','email','form','telegram','discord'))
          AND v.org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log)
          AND v.org_id NOT IN (SELECT org_id FROM defi4refi.drafts)
          AND v.org_id NOT IN (SELECT org_id FROM defi4refi.suppression)
          AND v.org_id NOT IN (SELECT org_id FROM defi4refi.suppression_auto)
        ORDER BY (v.sources LIKE '%artizen%') DESC, v.score DESC LIMIT {top_n}""")
    print(f"drafting for {len(orgs)} orgs")
    batch = []
    for o in orgs:
        contacts = rows(f"SELECT channel, value FROM defi4refi.contacts WHERE org_id='{o['org_id']}'")
        ch, val = pick_channel(contacts)
        if not ch:
            continue
        reason = (o.get("llm_reason") or "")[:200]
        artizen = "artizen" in (o.get("sources") or "")
        prompt = f"""You are 'defi4refi' — a free, open-source dev studio for ReFi/public-goods teams —
reaching out to an org that may need engineering help.
Write TWO different opening lines (each under 25 words) referencing something real about them.
Then TWO different 2-sentence pitches: we build protocol codebases (staking, treasuries, bonds,
governance) free and open-source; they can submit their idea via our GitHub page
(github.com/TerexitariusStomp) or join the community at t.me/defi4refi.
{"They were an Artizen Season 7 project — if relevant, gently acknowledge that expected funding may not have landed and we ship anyway." if artizen else ""}
Tone: peer-to-peer, concrete, zero hype. Never claim donations are tax-deductible.

Return JSON with these exact keys:
{{
  "open_a": "opening line variant A",
  "body_a": "pitch body variant A",
  "open_b": "opening line variant B",
  "body_b": "pitch body variant B"
}}

Org: {o['canonical_name']}
Funding: ${o['funding_usd']:,.0f} received ~{o['days_since_funded']} days ago
LLM reason: {reason}
Sources: {o['sources']}
Channel: {CH_PATH.get(ch, ch)}"""
        resp = llm(prompt, n=200)
        try:
            j = json.loads(resp)
            variants = [
                {"open_line": str(j.get("open_a", "")[:200]), "body": str(j.get("body_a", "")[:500])},
                {"open_line": str(j.get("open_b", "")[:200]), "body": str(j.get("body_b", "")[:500])},
            ]
        except Exception:
            variants = [
                {"open_line": f"Hi {o['canonical_name']} team — we build free open-source protocol code for ReFi projects",
                 "body": "Staking, treasuries, bonds, governance — shipped free. Submit your idea via github.com/TerexitariusStomp or join t.me/defi4refi."},
                {"open_line": f"Hey {o['canonical_name']} — saw your work in the ReFi space",
                 "body": "defi4refi ships free open-source protocol builds for public-goods teams. Apply via github.com/TerexitariusStomp or join t.me/defi4refi."},
            ]
        # pick variant A as the one to send (variant B is held for A/B comparison)
        selected = variants[0]
        withheld = variants[1]
        # insert draft (single row, the one to send)
        batch.append({"org_id": o["org_id"], "channel": ch, "contact": val,
                      "open_line": selected["open_line"], "body": selected["body"]})
        # insert variant log (both variants recorded, selected=A; sent_at defaults to now())
        ins_var([{"org_id": o["org_id"], "variant": 0, "open_line": selected["open_line"],
                  "body": selected["body"], "selected": True},
                 {"org_id": o["org_id"], "variant": 1, "open_line": withheld["open_line"],
                  "body": withheld["body"], "selected": False}])
        # also insert to drafts table for the send pipeline
        ins([{"org_id": o["org_id"], "channel": ch, "contact": val,
              "open_line": selected["open_line"], "body": selected["body"]}])
    print(f"drafted {len(batch)} orgs with A/B variants")

# ---- 2. TRIAGE: classify replies + record outcomes ----
def triage():
    pending = rows("SELECT org_id, body FROM defi4refi.replies WHERE reply_class=''")
    print(f"triaging {len(pending)} pending replies")
    for r in pending:
        prompt = f"""Classify this outreach reply into exactly one:
interested | question | not_now | negative | wrong_person

Return JSON: {{"class": "...", "conf": 0.0-1.0}}

Reply: {r['body'][:800]}"""
        resp = llm(prompt, n=60)
        try:
            j = json.loads(resp)
            cls = str(j.get("class", "")).strip()
            conf = float(j.get("conf", 0.5))
        except Exception:
            cls, conf = "unknown", 0.0
        if cls:
            ch_q(f"""ALTER TABLE defi4refi.replies
                UPDATE reply_class='{cls}', reply_conf={conf}
                WHERE org_id='{r['org_id']}' AND reply_class=''""")
        # record org outcome
        days = rows(f"SELECT toInt32(days_since_funded) FROM defi4refi.v_scored WHERE org_id='{r['org_id']}'")
        d = days[0]["days_since_funded"] if days else 0
        # find first contact date from outreach_log
        first = rows(f"SELECT min(sent_at) FROM defi4refi.outreach_log WHERE org_id='{r['org_id']}'")
        fc = first[0]["min(sent_at)"] if first and first[0]["min(sent_at)"] else None
        ins_octo([{"org_id": r["org_id"], "replied": True,
                   "reply_class": cls, "days_to_reply": d}
                  | ({"first_contact": fc} if fc else {})])

# ---- 3. LEARN: compute metrics, auto-suppress, re-rank ----
def learn(min_sends=20, dead_rate=0.0):
    print("running learning pass...")
    # ---- per-channel reply rates ----
    cperf = rows("""SELECT cp.channel, cp.sends, cp.replies,
        round(cp.replies / greatest(cp.sends,1), 3) AS rate
        FROM defi4refi.channel_perf cp
        ORDER BY cp.sends DESC""")
    print(f"  channel_perf: {len(cperf)} channels tracked")
    for c in cperf:
        flag = "  ⚠ DEAD" if (c["sends"] >= min_sends and c["rate"] <= dead_rate) else ""
        print(f"    {c['channel']:12} sends={c['sends']:4} replies={c['replies']:3} rate={c['rate']:.3f}{flag}")

    # ---- auto-suppress dead channels ----
    dead = rows(f"""SELECT cp.channel, count() AS n
        FROM defi4refi.channel_perf cp
        WHERE cp.sends >= {min_sends} AND cp.replies / greatest(cp.sends,1) <= {dead_rate}
        GROUP BY cp.channel""")
    if dead:
        print(f"  auto-suppressing {len(dead)} dead channels")
        for d in dead:
            # suppress all orgs that were contacted via this channel and got no replies
            orgs = rows(f"""SELECT DISTINCT d.org_id
                FROM defi4refi.drafts d
                LEFT JOIN defi4refi.outreach_log ol ON ol.org_id=d.org_id AND ol.channel=d.channel
                LEFT JOIN defi4refi.replies r ON r.org_id=d.org_id
                WHERE d.channel='{d['channel']}'
                  AND (r.org_id IS NULL OR r.reply_class IN ('negative','wrong_person','not_now'))
                  AND d.org_id NOT IN (SELECT org_id FROM defi4refi.suppression)
                  AND d.org_id NOT IN (SELECT org_id FROM defi4refi.suppression_auto
                                        WHERE channel='{d['channel']}')""")
            if orgs:
                ins_supp([{"org_id": o["org_id"], "channel": d["channel"],
                           "reason": f"auto: {d['channel']} {d['n']} sends 0 effective replies",
                           "suppressed_at": "now()", "suppress_count": 1} for o in orgs])
                print(f"    suppressed {len(orgs)} orgs on {d['channel']}")

    # ---- per-template (variant A vs B) reply rates ----
    # backfill replied flag on the sent variant from org_outcomes
    ch_q("""ALTER TABLE defi4refi.draft_variant_log
        UPDATE replied = 1
        WHERE selected = true AND replied = 0
          AND org_id IN (SELECT org_id FROM defi4refi.org_outcomes
                         WHERE replied = true
                           AND reply_class NOT IN ('negative','wrong_person'))""")
    variants = rows("""SELECT variant, count() AS sends, sum(replied) AS replies,
        round(sum(replied) / greatest(count(),1), 3) AS rate
        FROM defi4refi.draft_variant_log
        GROUP BY variant ORDER BY variant""")
    if variants:
        print(f"  draft variants: {variants[0]['sends']} A sends, {variants[1]['sends']} B sends")
        for v in variants:
            print(f"    variant {v['variant']}: {v['sends']} sends, {v['replies']} replies, rate={v['rate']:.3f}")

    # ---- org outcomes summary ----
    outcomes = rows("""SELECT reply_class, count() AS n
        FROM defi4refi.org_outcomes
        WHERE replied = true
        GROUP BY reply_class ORDER BY n DESC""")
    print(f"  org outcomes: {sum(o['n'] for o in outcomes)} replies")
    for o in outcomes:
        print(f"    {o['reply_class']:15} {o['n']}")

    # ---- score boost for domains/sources that get replies ----
    # Find orgs that replied "interested" or "question" and note their source/domain
    hot = rows("""SELECT distinct s.sources, s.domain, count() AS n
        FROM defi4refi.org_outcomes oo
        JOIN defi4refi.v_scored s ON s.org_id = oo.org_id
        WHERE oo.reply_class IN ('interested','question')
        GROUP BY s.sources, s.domain
        ORDER BY n DESC LIMIT 10""")
    if hot:
        print(f"  hot sources/domains (reply boost candidates):")
        for h in hot:
            print(f"    {h['sources'] or '(no source)'} | {h['domain'] or '(no domain)'} | {h['n']} replies")

# ---- 4. REPORT: current learning state ----
def report():
    print("=== Self-Improvement State ===")
    # channels
    chs = rows("""SELECT channel, sends, replies,
        round(replies / greatest(sends,1), 3) AS rate,
        if(sends >= 20 AND replies / greatest(sends,1) <= 0.01, 'DEAD', '') AS flag
        FROM defi4refi.channel_perf
        ORDER BY sends DESC""")
    print(f"\n--- Channel Performance ({len(chs)} tracked) ---")
    for c in chs:
        print(f"  {c['channel']:12} sends={c['sends']:4} replies={c['replies']:3} rate={c['rate']:.3f} {c['flag']}")
    # empirical priority
    print(f"\n--- Empirical Channel Priority ---")
    print("  " + " > ".join(empirical_channels()))
    # org outcomes
    outs = rows("""SELECT reply_class, count() AS n
        FROM defi4refi.org_outcomes WHERE replied=true GROUP BY reply_class ORDER BY n DESC""")
    total = sum(o["n"] for o in outs)
    print(f"\n--- Org Outcomes ({total} replies) ---")
    for o in outs:
        print(f"  {o['reply_class']:15} {o['n']}")
    # suppression
    supp = rows("SELECT count() FROM defi4refi.suppression_auto")
    print(f"\n--- Auto-Suppression ---")
    print(f"  auto-suppressed orgs: {supp[0]['count()']}")
    # queue
    qd = rows("SELECT count() FROM defi4refi.outreach_queue")
    print(f"\n--- Queue ---")
    print(f"  queued orgs: {qd[0]['count()']}")
    qenv = rows("""SELECT count() FROM defi4refi.outreach_queue v
        JOIN defi4refi.v_scored s ON s.org_id=v.org_id WHERE s.regen_fit>0""")
    print(f"  env-aligned in queue: {qenv[0]['count()']}")
    # drafts
    dr = rows("SELECT count() FROM defi4refi.drafts WHERE length(body) > 10 AND approved=0")
    print(f"  drafts ready: {dr[0]['count()']}")
    # sent
    sent = rows("SELECT count() FROM defi4refi.outreach_log")
    print(f"  sent: {sent[0]['count()']}")

# ---- entry point ----
if __name__ == "__main__":
    ensure_schema()
    actions = {"draft": draft, "triage": triage, "learn": learn, "report": report}
    for a in (sys.argv[1:] or ["draft"]):
        if a in actions:
            actions[a]()
        else:
            print(f"unknown action: {a} (choices: {list(actions.keys())})", file=sys.stderr)
print("AGENT DONE")
