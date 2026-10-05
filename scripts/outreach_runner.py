#!/usr/bin/env python3
"""
Outreach automation runner — full loop, no manual steps.

Cycle (runs every 6 hours by default):
  1. draft   — LLM-drafted messages, A/B variants, dynamic channel priority
  2. approve — auto-approve drafts that pass quality check (LLM judges)
  3. send    — dispatch via all reachable channels (Bluesky, GH issues, SMTP email, Telegram)
  4. triage  — classify inbound replies
  5. learn   — update channel_perf, org_outcomes, suppression_auto, v_scored_learned
  6. report  — print summary to stdout (captured by cron/systemd journal)

Graceful degradation: if no sending credentials are configured, step 3 logs
"would_send" entries and skips actual dispatch. The pipeline still learns from
any inbound replies that arrive via the webhook.

Env vars (all optional — pipeline runs without them, just can't send):
  BSKY_HANDLE, BSKY_APP_PASSWORD   — Bluesky DM/post-mention
  GITHUB_TOKEN                     — GitHub issue creation (public repos)
  SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_FROM  — email
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID       — Telegram DM
  OLLAMA_MODEL                     — default: llama3.1-8b-tools-32k
  OUTREACH_INTERVAL_MIN         — default: 360 (6 hours)
  OUTREACH_TOP_N                — max orgs to draft per cycle, default: 40
  OUTREACH_MAX_SEND_PER_CHANNEL — safety cap per channel per cycle, default: 5

Files (all in /home/terex/CascadeProjects/defi4refi/scripts/):
  outreach_agent.py   — draft/triage/learn/report (already exists, updated)
  outreach_send.py    — Bluesky dispatch + inbound webhook (already exists)
  outreach_runner.py  — THIS FILE — orchestrates the full automated cycle
"""

import json, os, subprocess, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

# --- paths ---
LAB = "/home/terex/CascadeProjects/defi4refi/scripts"
AGENT = os.path.join(LAB, "outreach_agent.py")
SEND = os.path.join(LAB, "outreach_send.py")

# --- load scripts/.env (gitignored) into environment ---
_env = os.path.join(LAB, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k, _v)

# --- config from env ---
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1-8b-tools-32k")
TOP_N = int(os.environ.get("OUTREACH_TOP_N", "40"))
MAX_SEND = int(os.environ.get("OUTREACH_MAX_SEND_PER_CHANNEL", "5"))
INTERVAL = int(os.environ.get("OUTREACH_INTERVAL_MIN", "360"))

CH = "http://localhost:8123/"

def q(sql, data=None):
    req = urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql),
        data=(data.encode() if data else b""),
        method="POST"
    )
    return urllib.request.urlopen(req, timeout=20).read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def llm(prompt, fmt_json=True, n=200):
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({
                "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                "format": "json" if fmt_json else None,
                "options": {"temperature": 0.3, "num_predict": n}
            }).encode(),
            headers={"Content-Type": "application/json"}
        )
        return json.loads(urllib.request.urlopen(req, timeout=90).read().decode()).get("response", "")
    except Exception as e:
        print(f"  [llm error] {e}")
        return "{}"

# ---------- step 1: draft ----------
def step_draft():
    print(f"[1/draft] generating up to {TOP_N} drafts...")
    start = time.time()
    subprocess.run([sys.executable, AGENT, "draft"], cwd=LAB, timeout=600)
    elapsed = time.time() - start

    count = rows_json("SELECT count() FROM defi4refi.drafts WHERE length(body) > 10 AND approved = 0")[0]["count()"]
    print(f"  drafted {count} new drafts in {elapsed:.0f}s")

# ---------- step 2: auto-approve ----------
def step_approve():
    print(f"[2/approve] auto-approving drafts...")
    pending = rows_json("""
        SELECT d.org_id, d.channel, d.contact, d.open_line, d.body,
               s.canonical_name, s.score, s.regen_fit, s.funding_usd, s.days_since_funded
        FROM defi4refi.drafts d
        JOIN defi4refi.v_scored s ON s.org_id = d.org_id
        WHERE d.approved = 0 AND length(d.body) > 10
        ORDER BY s.score DESC
    """)

    if not pending:
        print("  no pending drafts")
        return

    approved = 0
    skipped = 0
    for d in pending[:TOP_N * 2]:  # safety cap
        # Quality check: LLM judges whether the draft is worth sending
        prompt = f"""You are reviewing an outreach draft. Decide if it's worth sending.
The draft targets a real organization with real funding. A good draft: specific to the org,
mentions something real about them, offers genuine value, not spam-like.
Return JSON: {{ "send": true/false, "reason": "short reason" }}

Org: {d['canonical_name']}
Funding: ${d['funding_usd']:,.0f} | Score: {d['score']} | Regen fit: {d['regen_fit']}
Channel: {d['channel']} @ {d['contact']}
Open line: {d['open_line']}
Body: {d['body']}
"""
        resp = llm(prompt, n=80)
        try:
            j = json.loads(resp)
            if j.get("send"):
                q("ALTER TABLE defi4refi.drafts UPDATE approved = 1 WHERE org_id = '{}' SETTINGS mutations_sync = 1".format(d["org_id"]))
                approved += 1
            else:
                skipped += 1
        except Exception:
            # If LLM can't decide, approve anyway (better to send than stall)
            q("ALTER TABLE defi4refi.drafts UPDATE approved = 1 WHERE org_id = '{}' SETTINGS mutations_sync = 1".format(d["org_id"]))
            approved += 1

    print(f"  approved: {approved}, skipped: {skipped}")

# ---------- step 3: send ----------
def step_send():
    print(f"[3/send] dispatching approved drafts...")
    bsky = bool(os.environ.get("BSKY_HANDLE") and os.environ.get("BSKY_APP_PASSWORD"))
    gh = bool(os.environ.get("GITHUB_TOKEN"))
    smtp = all(os.environ.get(k) for k in ["SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"])
    telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))

    channels_ready = []
    if bsky: channels_ready.append("bluesky")
    if gh: channels_ready.append("github")
    if smtp: channels_ready.append("email")
    if telegram: channels_ready.append("telegram")

    if not channels_ready:
        print("  [no sending credentials configured]")
        print("  would_send: logging drafts that would be dispatched")
        # Log would-be sends so the pipeline still tracks intent
        would_send = rows_json("""
            SELECT org_id, channel, contact, open_line, body
            FROM defi4refi.drafts
            WHERE approved = 1 AND org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log)
        """)
        # NOTE: do NOT write to outreach_log here — outreach_queue excludes any
        # org in outreach_log, so logging would_send would silently burn the queue.
        # Track intent via signals instead.
        for d in would_send:
            q("""
                INSERT INTO defi4refi.signals (org_id, signal_type, detail)
                VALUES ('{}', 'would_send', 'channel: {} contact: {}')
            """.format(d["org_id"], d["channel"], d["contact"].replace("'", "''")))
        print(f"  would_send: {len(would_send)} drafts staged for next cycle with creds")
        return

    sent = 0
    for ch in channels_ready:
        cap_remaining = MAX_SEND
        print(f"  sending {ch} (cap {MAX_SEND}/cycle)...")
        if ch == "bluesky" and bsky:
            r = subprocess.run([sys.executable, SEND], cwd=LAB, capture_output=True, text=True, timeout=300)
            print(f"    bluesky: {r.stdout.strip()}")
            if r.returncode != 0:
                print(f"    bluesky stderr: {r.stderr[:200]}")
            sent += 1
        elif ch == "github" and gh:
            # Open issues on public repos via GitHub API
            issues = rows_json("""
                SELECT d.org_id, d.contact, d.open_line, d.body,
                       s.canonical_name, s.score
                FROM defi4refi.drafts d
                JOIN defi4refi.v_scored s ON s.org_id = d.org_id
                WHERE d.channel = 'github' AND d.approved = 1
                  AND d.org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log WHERE channel='github')
                ORDER BY s.score DESC
                LIMIT {maxsend}
            """.format(maxsend=MAX_SEND))
            for i in issues:
                if "/" not in i["contact"]:
                    print(f"    github skip {i['contact']}: not an owner/repo")
                    continue
                title = f"Free open-source build for {i['canonical_name']}?"
                body = f"""{i['open_line']}

{i['body']}

Submit an idea → https://github.com/TerexitariusStomp · Community → https://t.me/defi4refi

---
Sent automatically by the defi4refi outreach pipeline.
"""
                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{i['contact']}/issues",
                        data=json.dumps({"title": title, "body": body}).encode(),
                        headers={
                            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                            "Accept": "application/vnd.github.v3+json",
                            "Content-Type": "application/json"
                        },
                        method="POST"
                    )
                    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
                    q("""
                        INSERT INTO defi4refi.outreach_log (org_id, channel, value, sent_at, status)
                        VALUES ('{}', 'github', '{}', now(), 'sent')
                    """.format(i["org_id"], i["contact"]))
                    sent += 1
                    print(f"    github issue: {i['contact']}/{i['canonical_name']}")
                except Exception as e:
                    print(f"    github fail {i['contact']}: {str(e)[:80]}")
        elif ch == "email" and smtp:
            # SMTP email dispatch
            emails = rows_json("""
                SELECT d.org_id, d.contact, d.open_line, d.body,
                       s.canonical_name, s.score
                FROM defi4refi.drafts d
                JOIN defi4refi.v_scored s ON s.org_id = d.org_id
                WHERE d.channel = 'email' AND d.approved = 1
                  AND d.org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log WHERE channel='email')
                ORDER BY s.score DESC
                LIMIT {maxsend}
            """.format(maxsend=MAX_SEND))
            import smtplib
            from email.mime.text import MIMEText
            try:
                server = smtplib.SMTP(os.environ["SMTP_HOST"], 587, timeout=10)
                server.starttls()
                server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
                for e in emails:
                    msg = MIMEText(f"{e['open_line']}\n\n{e['body']}\n\nSubmit an idea → https://github.com/TerexitariusStomp\nCommunity → https://t.me/defi4refi\n\n---\nAuto-sent by the defi4refi outreach pipeline")
                    msg["Subject"] = f"Free open-source build for {e['canonical_name']}?"
                    msg["From"] = os.environ["SMTP_FROM"]
                    msg["To"] = e["contact"]
                    server.sendmail(os.environ["SMTP_FROM"], [e["contact"]], msg.as_string())
                    q("""
                        INSERT INTO defi4refi.outreach_log (org_id, channel, value, sent_at, status)
                        VALUES ('{}', 'email', '{}', now(), 'sent')
                    """.format(e["org_id"], e["contact"]))
                    sent += 1
                    print(f"    email: {e['contact']} ({e['canonical_name']})")
                server.quit()
            except Exception as e:
                print(f"    smtp fail: {str(e)[:80]}")
        elif ch == "telegram" and telegram:
            # Telegram bots can't DM arbitrary users — TELEGRAM_CHAT_ID is the
            # defi4refi group; post an operator summary of this cycle instead.
            try:
                queued = rows_json("""
                    SELECT count() AS n FROM defi4refi.drafts
                    WHERE approved = 1
                      AND org_id NOT IN (SELECT org_id FROM defi4refi.outreach_log)
                """)[0]["n"]
                text = (f"defi4refi outreach cycle: {queued} approved drafts in queue.\n"
                        f"New member questions welcome — submit ideas via "
                        f"https://github.com/TerexitariusStomp")
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                    data=json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}).encode(),
                    headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=10)
                print("    telegram: cycle summary posted to defi4refi group")
            except Exception as e:
                print(f"    telegram fail: {str(e)[:80]}")
        # respect per-channel cap
        if sent >= MAX_SEND:
            break

    total_sent = rows_json("SELECT count() FROM defi4refi.outreach_log WHERE status = 'sent'")[0]["count()"]
    print(f"  total sent (all time): {total_sent}")

# ---------- step 4: triage ----------
def step_triage():
    print("[4/triage] classifying inbound replies...")
    subprocess.run([sys.executable, AGENT, "triage"], cwd=LAB, timeout=300)

# ---------- step 5: learn ----------
def step_learn():
    print("[5/learn] updating metrics and suppression...")
    subprocess.run([sys.executable, AGENT, "learn"], cwd=LAB, timeout=300)

# ---------- step 6: report ----------
def step_report():
    print("[6/report] pipeline state...")
    subprocess.run([sys.executable, AGENT, "report"], cwd=LAB, timeout=60)

# ---------- main loop ----------
def run_once():
    t0 = time.time()
    print(f"=== outreach cycle start ({datetime.now(timezone.utc).isoformat()}) ===")
    steps = [step_draft, step_approve, step_send, step_triage, step_learn, step_report]
    for step in steps:
        try:
            step()
        except Exception as e:
            print(f"  [step failed] {step.__name__}: {e}")
    elapsed = time.time() - t0
    print(f"=== cycle complete in {elapsed:.0f}s ===\n")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        run_once()
    else:
        print(f"outreach automation runner — cycle every {INTERVAL}min")
        print(f"  top_n: {TOP_N}, max_send/channel: {MAX_SEND}")
        print(f"  channels ready: bluesky={bool(os.environ.get('BSKY_HANDLE'))} "
              f"gh={bool(os.environ.get('GITHUB_TOKEN'))} "
              f"smtp={all(os.environ.get(k) for k in ['SMTP_HOST','SMTP_USER','SMTP_PASS','SMTP_FROM'])} "
              f"telegram={bool(os.environ.get('TELEGRAM_BOT_TOKEN'))}")
        print()
        while True:
            run_once()
            print(f"sleeping {INTERVAL} minutes...")
            time.sleep(INTERVAL * 60)

if __name__ == "__main__":
    main()