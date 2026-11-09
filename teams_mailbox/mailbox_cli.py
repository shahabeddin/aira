#!/usr/bin/env python3
"""Mailbox CLI for inter-team messaging. JSONL inboxes under tmp/teams_mailbox/<team>/inbox.jsonl.

Message schema: {id, from, to:[...all recipients...], subject, body, ts, read, reply_to?}
Every copy carries the FULL `to` list, so each recipient sees who else got the message.
reply_all replies to the whole original audience (from ∪ to minus self).

Subcommands:
  send <recipients> <message...> [--subject S] [--from T]
      recipients = comma-separated teams (supervisor|data|modeling|quality) or `all`
  reply_all <orig_id> <reply...> [--from T]   # reply to all recipients of orig message
  list [team] [--unread]                       # show a team's inbox (subject + metadata only)
  read <team> <id>                             # print ONE message's full body (+ headers)
  mark_read <team> <id>                         # mark one message read
"""
import json, os, sys, time, pathlib, argparse, fcntl
from contextlib import contextmanager

# Default store = the 'default' project, created empty on first use. Override the data
# dir with AGENT_TEAM_MAILBOX; --project/AGENT_TEAM_PROJECT scopes to projects/<name>/.
_REPO = pathlib.Path(__file__).resolve().parents[1]
MAILBOX = pathlib.Path(os.environ.get("AGENT_TEAM_MAILBOX")
    or str(_REPO / "projects" / "default" / "teams_mailbox"))

# --- project-scoped stores (added 2026-09-03; fully backward-compatible) -------------
# Optional: --project <name> (works on any subcommand) or AGENT_TEAM_PROJECT env.
# When set, inboxes resolve under AGENT_TEAM_PROJECTS_ROOT/<name>/teams_mailbox (default
# root: <repo>/projects), created empty on first use. Project operations never touch the
# legacy store; with no project given, behavior is exactly the pre-existing path.
_argv, _pv, _i = [], None, 0
while _i < len(sys.argv):
    _a = sys.argv[_i]
    if _a == "--project" and _i + 1 < len(sys.argv):
        _pv = sys.argv[_i + 1]; _i += 2; continue
    if _a.startswith("--project="):
        _pv = _a.split("=", 1)[1]; _i += 1; continue
    _argv.append(_a); _i += 1
sys.argv = _argv
_PROJECT = _pv or os.environ.get("AGENT_TEAM_PROJECT", "")
if _PROJECT:
    if not _PROJECT.replace("-", "").replace("_", "").isalnum():
        sys.exit("invalid project name (letters/digits/-/_ only)")
    _root = pathlib.Path(os.environ.get("AGENT_TEAM_PROJECTS_ROOT")
        or str(pathlib.Path(__file__).resolve().parents[1] / "projects"))
    MAILBOX = _root / _PROJECT / "teams_mailbox"
# --- team registry (added 2026-09-04; replaces the hardcoded TEAMS list) -------------
# Teams are discovered from projects/<name>/teams/<team>.json manifests (shared with
# ticket_cli). Each manifest: {"name","role":"verifier"|"coordinator"|"worker",...}.
# If no registry exists (legacy store / pre-registry project), teams are discovered by
# scanning mailbox inbox dirs, with conventional roles applied (quality->verifier,
# supervisor->coordinator, scouting->coordinator legacy). This keeps the live project
# working unchanged.
_PROJECT_ROOT = pathlib.Path(os.environ.get("AGENT_TEAM_PROJECTS_ROOT")
    or str(pathlib.Path(__file__).resolve().parents[1] / "projects"))

def _teams_dir():
    if _PROJECT:
        return _PROJECT_ROOT / _PROJECT / "teams"
    return None

def load_teams():
    """Return {name: manifest}. Falls back to inbox-dir discovery if no registry."""
    td = _teams_dir()
    teams = {}
    if td and td.exists():
        for f in sorted(td.glob("*.json")):
            try:
                m = json.loads(f.read_text())
                teams[m.get("name", f.stem)] = m
            except Exception:
                continue
    if teams:
        return teams
    # fallback: discover from existing inboxes (mailbox can't see ticket team fields)
    names = sorted(d.parent.name for d in MAILBOX.glob("*/inbox.jsonl")) if MAILBOX.exists() else []
    conv = {"quality": "verifier", "supervisor": "coordinator", "scouting": "coordinator"}
    return {n: {"name": n, "role": conv.get(n, "worker")} for n in names}

def team_names():
    return list(load_teams().keys())

def actor():
    """Who is issuing this command. Precedence:
    --by/--from flag (sets CLAUDE_TEAM) > CLAUDE_TEAM env (launch-time, session-scoped)
    > <cwd>/.current_team (written by /set-team) > ~/.config/aira/current_team
    > "unknown". Env wins over file so parallel sessions aren't clobbered by a shared file."""
    v = os.environ.get("CLAUDE_TEAM")
    if v: return v
    cf = pathlib.Path.cwd() / ".current_team"
    if cf.exists():
        v = cf.read_text().strip()
        if v: return v
    gf = pathlib.Path.home() / ".config" / "aira" / "current_team"
    if gf.exists():
        v = gf.read_text().strip()
        if v: return v
    return "unknown"
def now(): return int(time.time())

def resolve_recips(arg):
    arg = arg.strip()
    if arg == "all":
        return [t for t in team_names() if t != actor()]
    recips = [t.strip() for t in arg.split(",") if t.strip()]
    known = team_names()
    for r in recips:
        if r not in known:
            sys.exit(f"bad team {r!r} (known: {known} or 'all')")
    return recips

@contextmanager
def team_lock(team):
    """Exclusive flock on a per-team sidecar lock file. Serializes mark_read's
    load+atomic-rewrite against send/reply_all appends on the SAME inbox, so a
    concurrent append can't be silently clobbered by the rewrite (and vice versa).
    Lock is on a separate .lock file, not the inbox itself, so atomic replace of
    inbox.jsonl never invalidates the open lock handle."""
    mb = MAILBOX / team
    mb.mkdir(parents=True, exist_ok=True)
    lf = open(mb / "inbox.jsonl.lock", "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()

def append_copy(team, msg):
    with team_lock(team):
        mb = MAILBOX / team / "inbox.jsonl"
        mb.parent.mkdir(parents=True, exist_ok=True)
        with open(mb, "a") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.flush()

def load_inbox(team):
    mb = MAILBOX / team / "inbox.jsonl"
    if not mb.exists(): return []
    out = []
    for l in mb.read_text().splitlines():
        l = l.strip()
        if not l: continue
        try: out.append(json.loads(l))
        except json.JSONDecodeError: continue  # skip half-written last line from a prior crash
    return out

def save_inbox(team, rows):
    mb = MAILBOX / team / "inbox.jsonl"
    tmp = mb.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(mb)

def to_list(m):
    to = m.get("to", [])
    return to if isinstance(to, list) else [to]

def cmd_send(a):
    sender = a.from_ or actor()
    recips = resolve_recips(a.recipients)
    if sender in recips:
        recips = [r for r in recips if r != sender]  # don't self-cc
    if not recips:
        sys.exit("no recipients (sender excluded all)")
    ts = now()
    body = " ".join(a.message)
    for i, r in enumerate(recips):
        msg = {"id": f"{sender}-{ts}-{r[:3]}{i}", "from": sender, "to": recips,
               "subject": a.subject or "(no subject)", "body": body, "ts": ts, "read": False}
        append_copy(r, msg)
    print(f"Sent to {len(recips)}: {', '.join(recips)} | {a.subject or '(no subject)'}")

def cmd_reply_all(a):
    sender = a.from_ or actor()
    rows = load_inbox(sender)
    orig = None
    for m in rows:
        if m.get("id") == a.orig_id:
            orig = m; break
    if orig is None:
        sys.exit(f"message {a.orig_id} not found in {sender} inbox")
    audience = set([orig["from"]] + to_list(orig))
    audience.discard(sender)
    targets = [t for t in team_names() if t in audience]
    if not targets:
        sys.exit("no reply targets (you were the only original recipient?)")
    ts = now()
    body = " ".join(a.reply)
    for i, r in enumerate(targets):
        msg = {"id": f"{sender}-{ts}-re-{r[:3]}{i}", "from": sender, "to": targets,
               "subject": f"re: {orig.get('subject', '(no subject)')}", "body": body,
               "ts": ts, "read": False, "reply_to": orig["id"]}
        append_copy(r, msg)
    print(f"Reply-all to {len(targets)}: {', '.join(targets)} | re: {orig.get('subject')}")

def cmd_list(a):
    team = a.team or actor()  # default to the acting team's own inbox
    for m in load_inbox(team):
        if a.unread and m.get("read"): continue
        to = ", ".join(to_list(m))
        flag = "UNREAD" if not m.get("read") else "read"
        print(f"{m['id']}  from={m['from']}  to=[{to}]  {flag}  {m.get('subject')}")

def cmd_mark_read(a):
    with team_lock(a.team):
        rows = load_inbox(a.team)
        for r in rows:
            if r.get("id") == a.id: r["read"] = True
        save_inbox(a.team, rows)
    print(f"marked {a.id} read in {a.team}")

def cmd_read(a):
    """Print ONE message's full body + headers without loading the whole inbox
    into the caller's context. Iterates the file line-by-line, prints the first
    match, stops. O(1 message) vs the prior pattern of cat-ing inbox.jsonl."""
    mb = MAILBOX / a.team / "inbox.jsonl"
    if not mb.exists():
        sys.exit(f"no inbox for {a.team}")
    with open(mb) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip half-written last line from a prior crash
            if m.get("id") != a.id:
                continue
            to = ", ".join(to_list(m))
            print(f"id: {m.get('id')}")
            print(f"from: {m.get('from')}")
            print(f"to: [{to}]")
            print(f"subject: {m.get('subject')}")
            print(f"read: {'yes' if m.get('read') else 'no'}")
            if m.get("reply_to"):
                print(f"reply_to: {m['reply_to']}")
            print("---")
            print(m.get("body", ""))
            return
    sys.exit(f"message {a.id} not found in {a.team} inbox")

p = argparse.ArgumentParser()
p.add_argument("--by", dest="from_", default=None, help="sender (overrides CLAUDE_TEAM)")
sub = p.add_subparsers(dest="cmd", required=True)

s = sub.add_parser("send"); s.add_argument("recipients"); s.add_argument("message", nargs="+")
s.add_argument("--subject", default=None)

r = sub.add_parser("reply_all"); r.add_argument("orig_id"); r.add_argument("reply", nargs="+")

l = sub.add_parser("list"); l.add_argument("team", nargs="?"); l.add_argument("--unread", action="store_true")

mr = sub.add_parser("mark_read"); mr.add_argument("team"); mr.add_argument("id")

rd = sub.add_parser("read"); rd.add_argument("team"); rd.add_argument("id")

args = p.parse_args()
if args.from_: os.environ["CLAUDE_TEAM"] = args.from_
{"send": cmd_send, "reply_all": cmd_reply_all, "list": cmd_list,
 "mark_read": cmd_mark_read, "read": cmd_read}[args.cmd](args)
