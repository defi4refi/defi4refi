#!/usr/bin/env python3
"""
Queue governor + learning pass for outreach pipeline.

Runs weekly (cron) or on-demand:

  1. queue depth check — keep outreach_queue >= 3x weekly batch
  2. channel_perf population — compute sends/replies per channel from drafts+log+replies
  3. org_outcome completeness — backfill org_outcomes for any replies not yet recorded
  4. learn() — auto-suppress dead channels, report hot sources
  5. escalation — if queue depth low, suggest next action
"""
import json, os, subprocess, sys, urllib.request, urllib.parse

CH = "http://localhost:8123/"
WEEKLY_BATCH = int(os.environ.get("WEEKLY_BATCH", "100"))
MIN_DEPTH = 3 * WEEKLY_BATCH

def ch_q(sql, data=None):
    return urllib.request.urlopen(
        urllib.request.Request(CH + "?query=" + urllib.parse.quote(sql),
                               data=(data.encode() if data else b""), method="POST")).read().decode()

def rows(sql):
    return [json.loads(l) for l in ch_q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def pop_channel_perf():
    """channel_perf is now a live VIEW over outreach_log+replies — nothing to populate."""
    return

def _pop_channel_perf_legacy():
    """Compute per-channel sends/replies from drafts + outreach_log + replies."""
    # sends: count of distinct org_ids sent per channel
    sends = rows("""SELECT d.channel, count() AS sends
        FROM defi4refi.drafts d
        JOIN defi4refi.outreach_log ol ON ol.org_id=d.org_id AND ol.channel=d.channel
        GROUP BY d.channel""")
    # replies: count of distinct org_ids that replied per channel
    replies = rows("""SELECT d.channel, count(DISTINCT r.org_id) AS replies
        FROM defi4refi.drafts d
        JOIN defi4refi.outreach_log ol ON ol.org_id=d.org_id AND ol.channel=d.channel
        LEFT JOIN defi4refi.replies r ON r.org_id=d.org_id AND r.reply_class!=''
        WHERE r.org_id IS NOT NULL
        GROUP BY d.channel""")
    send_map = {s["channel"]: s["sends"] for s in sends}
    reply_map = {r["channel"]: r["replies"] for r in replies}
    all_channels = set(send_map.keys()) | set(reply_map.keys())
    rows_to_ins = []
    for ch in all_channels:
        s = send_map.get(ch, 0)
        r = reply_map.get(ch, 0)
        rows_to_ins.append({"channel": ch, "sends": s, "replies": r,
                            "reply_rate": round(r / max(s,1), 3),
                            "first_sent": "now()", "last_sent": "now()",
                            "updated_at": "now()"})
    if rows_to_ins:
        ins = "\n".join(json.dumps(r) for r in rows_to_ins)
        ch_q("INSERT INTO defi4refi.channel_perf FORMAT JSONEachRow", data=ins)
    print(f"  channel_perf populated: {len(rows_to_ins)} channels")

def backfill_outcomes():
    """Ensure every reply with a class has a matching org_outcomes row."""
    existing = rows("SELECT org_id FROM defi4refi.org_outcomes")
    existing_set = {o["org_id"] for o in existing}
    pending = rows("""SELECT r.org_id, r.body, r.reply_class,
        toInt32(s.days_since_funded) AS days
        FROM defi4refi.replies r
        JOIN defi4refi.v_scored s ON s.org_id = r.org_id
        WHERE r.reply_class != '' AND r.org_id NOT IN ({})""".format(
        ",".join(f"'{o}'" for o in list(existing_set)[:1000])))
    if not pending:
        return
    for p in pending[:500]:
        first = rows(f"SELECT min(sent_at) FROM defi4refi.outreach_log WHERE org_id='{p['org_id']}'")
        fc = first[0]["min(sent_at)"] if first else None
        row = {"org_id": p["org_id"], "replied": True,
               "reply_class": p["reply_class"], "days_to_reply": p["days"]}
        if fc:
            row["first_contact"] = fc
        ch_q("INSERT INTO defi4refi.org_outcomes FORMAT JSONEachRow",
              data=json.dumps(row))
    print(f"  backfilled {len(pending)} org outcomes")

def run():
    print("=== Governor + Learning Pass ===")
    # 1. queue depth
    depth = int(ch_q("SELECT count() FROM defi4refi.outreach_queue"))
    total = int(ch_q("SELECT count() FROM defi4refi.orgs FINAL"))
    funded = int(ch_q("""SELECT uniq(org_id) FROM defi4refi.funding_events
        WHERE amount_usd>0 AND program!='token-market-cap'"""))
    print(f"queue depth: {depth} (min {MIN_DEPTH}) | orgs: {total} | funded: {funded}")

    if depth < MIN_DEPTH:
        escalations = [
            ("lower score threshold", "edit score gate 35→30 in outreach_queue.sql"),
            ("resume pagination", "python3 scripts/load_scale.py — deeper pages"),
            ("next bulk source", "load next registry: UK CC, CORDIS, CRA, NGO Darpan"),
            ("widen regions", "pull more non-US registries"),
        ]
        for i, (name, action) in enumerate(escalations):
            print(f"ESCALATION {i+1}: {name} — {action}")

    # 2. populate channel_perf
    print("\n--- populating channel_perf ---")
    pop_channel_perf()

    # 3. backfill outcomes
    print("\n--- backfilling org_outcomes ---")
    backfill_outcomes()

    # 4. learning report
    print("\n--- learning state ---")
    cperf = rows("""SELECT channel, sends, replies,
        round(replies / greatest(sends,1), 3) AS rate,
        if(sends >= 20 AND replies / greatest(sends,1) <= 0.01, 'DEAD', '') AS flag
        FROM defi4refi.channel_perf ORDER BY sends DESC""")
    for c in cperf:
        print(f"  {c['channel']:12} sends={c['sends']:4} replies={c['replies']:3} rate={c['rate']:.3f} {c['flag']}")

    # empirical priority
    HARDCODED = ["bluesky","mastodon","nostr","farcaster","matrix","github","email","telegram","discord","form","substack","twitter"]
    proven = [c["channel"] for c in cperf if c["sends"] >= 5]
    priority = proven if proven else HARDCODED[:]
    for ch in HARDCODED:
        if ch not in priority:
            priority.append(ch)
    print(f"\n  empirical priority: {' > '.join(priority)}")

    # org outcomes
    outs = rows("""SELECT reply_class, count() AS n
        FROM defi4refi.org_outcomes WHERE replied=true GROUP BY reply_class ORDER BY n DESC""")
    total_r = sum(o["n"] for o in outs)
    print(f"\n  org outcomes ({total_r} replies):")
    for o in outs:
        print(f"    {o['reply_class']:15} {o['n']}")

    # auto-suppression count
    supp = rows("SELECT count() FROM defi4refi.suppression_auto")
    print(f"\n  auto-suppressed orgs: {supp[0]['count()']}")

    # hot sources
    hot = rows("""SELECT distinct s.sources, count() AS n
        FROM defi4refi.org_outcomes oo
        JOIN defi4refi.v_scored s ON s.org_id = oo.org_id
        WHERE oo.reply_class IN ('interested','question')
        GROUP BY s.sources ORDER BY n DESC LIMIT 10""")
    if hot:
        print(f"\n  hot sources (reply boost):")
        for h in hot:
            print(f"    {h['sources'] or '(no source)'}: {h['n']} replies")

if __name__ == "__main__":
    run()
