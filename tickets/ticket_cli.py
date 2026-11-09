#!/usr/bin/env python3
"""Filesystem ticket system for teams of AI agent sessions.
One JSON file per ticket under tmp/tickets/T-XXXX.json. Done/cancelled tickets
archive to tmp/tickets/archive/YYYY-MM/. Create/reassign notifies the team mailbox.

Subcommands:
  new <team> <title...> [field flags] [--no-notify]
  list [team] [status] [--label L] [--epic E]
  board [--team T] [--epic E] [--recent N]   # curated tabular view (active + recent done/verified)
  show <id>
  status <id> <status> [--blocked-reason ...]
  assign <id> <team> [--no-notify]
  set <id> [field flags]            # update fields (epic/depends_on/labels/blocked_reason/priority/desc/title/team)
  comment <id> <text...>
  close <id>                        # status -> done
  duplicate <id> <of-id> [--archive]# mark id cancelled as dup of of-id
  archive <id> | archive --all-done # move to archive/YYYY-MM/
  stale [days]                      # open/in_progress untouched >= days (default 7)
  usage <id> [--model M] [--effort E] [--tokens N] [--platform P] [--note "..."]
                                     # log a self-reported LLM usage record (no cost calc)
Field flags (new/set): --desc --priority low|med|high --epic E --depends-on id1,id2
                       --label a,b --blocked-reason "..."  (use "-" to clear)
"""
import json, os, sys, time, pathlib, argparse

# Default store = the 'default' project, created empty on first use. Override the data
# dir with AGENT_TEAM_TICKETS; --project/AGENT_TEAM_PROJECT scopes to projects/<name>/.
_REPO = pathlib.Path(__file__).resolve().parents[1]
TICKETS = pathlib.Path(os.environ.get("AGENT_TEAM_TICKETS")
    or str(_REPO / "projects" / "default" / "tickets"))
MAILBOX = pathlib.Path(os.environ.get("AGENT_TEAM_MAILBOX")
    or str(_REPO / "projects" / "default" / "teams_mailbox"))

# --- project-scoped stores (added 2026-09-03; fully backward-compatible) -------------
# Optional: --project <name> (works on any subcommand) or AGENT_TEAM_PROJECT env.
# When set, ALL data resolves under AGENT_TEAM_PROJECTS_ROOT/<name>/{tickets,teams_mailbox}
# (default root: <repo>/projects). Project
# dirs are created empty on first use, and project operations NEVER touch the legacy store
# above — tickets are separated by directory, nothing is moved or deleted. With no project
# given, behavior is exactly
# the pre-existing AGENT_TEAM_TICKETS/AGENT_TEAM_MAILBOX path (live project unaffected).
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
    TICKETS = _root / _PROJECT / "tickets"
    MAILBOX = _root / _PROJECT / "teams_mailbox"
# --- team registry (added 2026-09-04; replaces the hardcoded TEAMS set) -------------
# Teams are discovered from projects/<name>/teams/<team>.json manifests. Each manifest:
#   {"name": "...", "role": "verifier"|"coordinator"|"worker", "color": "...", "description": "..."}
#   - role "verifier": the ONLY team allowed to set status=verified (the "verifier gate").
#     If NO team is declared verifier, the gate is OFF and anyone may verify.
#   - role "coordinator": the leadership/supervisor team (drives the `lead` skill; UI badge).
#     Informational only — no permission gate.
#   - role "worker" (default): a plain builder team.
# If no manifest dir exists (legacy store / pre-registry project), teams are DISCOVERED by
# scanning ticket `team` fields + mailbox inbox dirs, with the conventional roles applied
# (quality->verifier, supervisor->coordinator, scouting->coordinator legacy, everyone else
# ->worker). This keeps the live project working unchanged — no registry is written for it
# unless asked.
_PROJECT_ROOT = pathlib.Path(os.environ.get("AGENT_TEAM_PROJECTS_ROOT")
    or str(pathlib.Path(__file__).resolve().parents[1] / "projects"))

def _teams_dir():
    """Registry dir for the active project, or None in legacy (no-project) mode."""
    if _PROJECT:
        return _PROJECT_ROOT / _PROJECT / "teams"
    return None

def _has_registry():
    td = _teams_dir()
    return bool(td and td.exists() and any(td.glob("*.json")))

def load_teams():
    """Return {name: manifest}. Falls back to discovery if no registry exists."""
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
    # fallback: discover from existing data (legacy / pre-registry project)
    names = set()
    for f in TICKETS.glob("T-*.json"):
        try:
            t = json.loads(f.read_text())
            if t.get("team"): names.add(t["team"])
        except Exception:
            continue
    for d in MAILBOX.glob("*/inbox.jsonl"):
        if d.parent.name not in names: names.add(d.parent.name)
    conv = {"quality": "verifier", "supervisor": "coordinator", "scouting": "coordinator"}  # conventional roles; scouting is a legacy alias for supervisor
    return {n: {"name": n, "role": conv.get(n, "worker")} for n in sorted(names)}

def team_names():
    return list(load_teams().keys())

def verifier_team():
    """Name of the declared verifier team, or None (gate OFF)."""
    for name, m in load_teams().items():
        if m.get("role") == "verifier":
            return name
    return None

def save_team(name, role="worker", description=None):
    td = _teams_dir()
    if not td:
        sys.exit("team registry requires a project (use --project <name> or AGENT_TEAM_PROJECT)")
    td.mkdir(parents=True, exist_ok=True)
    m = {"name": name, "role": role}
    if description: m["description"] = description
    (td / f"{name}.json").write_text(json.dumps(m, indent=2))

def remove_team(name):
    td = _teams_dir()
    if not td: return
    f = td / f"{name}.json"
    if f.exists(): f.unlink()

STATUSES = {"backlog", "open", "in_progress", "blocked", "done", "verified", "cancelled"}
PLATFORMS = {"anthropic", "fireworks", "bedrock", "other"}
# usage records are self-reported (model/effort/tokens/platform), not audited or priced
# Workflow: backlog -> open -> in_progress -> (blocked) -> done -> verified
#   done    = builder finished, ready for Quality review
#   verified = Quality passed (terminal success)  [set only by Quality via `verify`]
#   QA fail -> `reopen <id> <reason>` -> in_progress + required reason comment
# Archive targets: verified | cancelled (NOT done, which still awaits QA)

def actor():
    """Who is issuing this command. Precedence:
    --by flag (sets CLAUDE_TEAM for this process) > CLAUDE_TEAM env (launch-time, session-scoped)
    > <cwd>/.current_team (written by /set-team; used when env wasn't set at launch)
    > ~/.config/aira/current_team (global default) > "unknown".
    Env wins over the file so parallel sessions (each launched with its own CLAUDE_TEAM)
    are never clobbered by a shared on-disk file."""
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
def days_since(ts): return (now() - ts) // 86400

def next_id():
    TICKETS.mkdir(parents=True, exist_ok=True)
    ids = [int(f.stem.split("-")[1]) for f in TICKETS.glob("T-*.json")]
    return f"T-{(max(ids)+1 if ids else 1):04d}"

def load(tid):
    p = TICKETS / f"{tid}.json"
    if not p.exists(): sys.exit(f"ticket {tid} not found")
    return json.loads(p.read_text())

def save(t):
    p = TICKETS / f"{t['id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(t, indent=2)); tmp.replace(p)

def add_history(t, frm, to, kind="status"):
    """Append a structured history entry alongside the comment trail. Older tickets
    have no `history` array; they get one on the next transition (additive, no migration)."""
    t.setdefault("history", []).append({"ts": now(), "by": actor(), "from": frm, "to": to, "kind": kind})

def notify(team, subject, body):
    if team not in team_names(): return
    mb = MAILBOX / team / "inbox.jsonl"; mb.parent.mkdir(parents=True, exist_ok=True)
    msg = {"id": f"ticket-{now()}-{team[:3]}", "from": actor(), "to": team,
           "subject": subject, "body": body, "ts": now(), "read": False}
    with open(mb, "a") as f: f.write(json.dumps(msg) + "\n")

def to_list(v):  # comma-separated -> list, "-" -> []
    v = v.strip()
    if v == "-" or v == "": return []
    return [x.strip() for x in v.split(",") if x.strip()]

def add_field_args(p):
    p.add_argument("--desc", default=None)
    p.add_argument("--priority", default=None, choices=[None, "low", "med", "high"])
    p.add_argument("--epic", default=None)
    p.add_argument("--depends-on", dest="depends_on", default=None)
    p.add_argument("--label", default=None)
    p.add_argument("--blocked-reason", dest="blocked_reason", default=None)
    p.add_argument("--ac", default=None, help="acceptance criteria (testable conditions for done)")

def apply_fields(t, a, comment):
    changed = []
    if a.desc is not None and a.desc != t.get("description"):
        t["description"] = a.desc; changed.append("desc")
    if a.priority and a.priority != t.get("priority"):
        t["priority"] = a.priority; changed.append(f"priority={a.priority}")
    if a.epic is not None and a.epic != t.get("epic"):
        t["epic"] = None if a.epic == "-" else a.epic; changed.append(f"epic={t['epic']}")
    if a.depends_on is not None:
        new = to_list(a.depends_on)
        if new != t.get("depends_on", []):
            t["depends_on"] = new; changed.append(f"depends_on={new}")
    if a.label is not None:
        new = to_list(a.label)
        if new != t.get("labels", []):
            t["labels"] = new; changed.append(f"labels={new}")
    if a.blocked_reason is not None and a.blocked_reason != t.get("blocked_reason"):
        t["blocked_reason"] = None if a.blocked_reason == "-" else a.blocked_reason
        changed.append(f"blocked_reason={t['blocked_reason']}")
    if a.ac is not None and a.ac != t.get("acceptance_criteria"):
        t["acceptance_criteria"] = a.ac
        changed.append("acceptance_criteria")
    if changed:
        t["updated"] = {"ts": now(), "by": actor()}
        comment(f"set: " + ", ".join(changed))
    return changed

def index_refresh():
    lines = ["# Tickets (active)", "",
             "| ID | Team | Status | Pri | Epic | Age | Title |",
             "|---|---|---|---|---|---|---|"]
    for f in sorted(TICKETS.glob("T-*.json")):
        t = json.loads(f.read_text())
        age = days_since(t["updated"]["ts"])
        lines.append(f"| {t['id']} | {t['team']} | {t['status']} | {t.get('priority','med')} | "
                     f"{t.get('epic') or '-'} | {age}d | {t['title']} |")
    (TICKETS / "INDEX.md").write_text("\n".join(lines) + "\n")

# --- subcommands ---
def cmd_new(a):
    # Acceptance criteria are required for projects using the governance registry
    # (created via the new system / /team-up). Legacy/pre-registry projects stay
    # lenient so the live project workflow is uninterrupted. --force bypasses.
    if _has_registry() and not (a.ac or "").strip() and not a.force:
        sys.exit("tickets need testable acceptance criteria (--ac \"...\"); use --force to override")
    if a.team not in team_names() and not a.force:
        sys.exit(f"bad team {a.team} (known: {sorted(team_names())}); use --force to register it implicitly")
    title = " ".join(a.title)
    tid = next_id()
    t = {"id": tid, "title": title, "description": a.desc or "", "team": a.team,
         "assignee": a.team, "status": a.status or "backlog", "priority": a.priority or "med",
         "epic": None if a.epic in (None,"-") else a.epic,
         "labels": to_list(a.label) if a.label else [], "depends_on": to_list(a.depends_on) if a.depends_on else [],
         "blocked_reason": None if a.blocked_reason in (None,"-") else a.blocked_reason,
         "acceptance_criteria": a.ac or "",
         "created": {"ts": now(), "by": actor()}, "updated": {"ts": now(), "by": actor()},
         "comments": [], "history": [], "usage": []}
    save(t); index_refresh()
    if a.notify:
        notify(a.team, f"New ticket {tid}: {title}",
               f"Ticket {tid} created by {actor()}, assigned to {a.team}, priority {t['priority']}"
               + (f", epic {t['epic']}" if t['epic'] else "") + ".\n"
               f"Title: {title}\nDescription: {t['description'] or '(none)'}\n"
               f"See tmp/tickets/{tid}.json. Update: ticket_cli.py status {tid} <status>")
    print(f"Created {tid} ({a.team}, {t['priority']}): {title}")

def cmd_list(a):
    for f in sorted(TICKETS.glob("T-*.json")):
        t = json.loads(f.read_text())
        if a.team and t["team"] != a.team: continue
        if a.status and t["status"] != a.status: continue
        if a.label and a.label not in t.get("labels", []): continue
        if a.epic and t.get("epic") != a.epic: continue
        print(f"{t['id']}  [{t['team']:8}]  {t['status']:11}  {t.get('priority','med'):4}  "
              f"{(t.get('epic') or '-'):24}  {days_since(t['updated']['ts'])}d  {t['title']}")

# Priority weight for sorting: high > med > low (active work first).
_PRI = {"high": 0, "med": 1, "low": 2, None: 1}

# Board fixed column content widths: ID, Team, Status, Pri, Age. Title width is dynamic.
_BW_FIXED = [6, 8, 11, 4, 4]
_TITLE_DEFAULT = 54  # title truncation width when not --full

def _trunc(s, w):
    s = s or ""
    return s if len(s) <= w else s[:w - 1] + "…"

def _bcell(c, cw):
    """One padded board cell (content width cw)."""
    c = str(c)
    if len(c) > cw:
        c = _trunc(c, cw)
    return " " + c.ljust(cw) + " "

def _brow(cells, w):
    return "│" + "│".join(_bcell(c, w[i]) for i, c in enumerate(cells)) + "│"

def _bborder(l, m, r, w):
    return l + m.join("─" * (w[i] + 2) for i in range(len(w))) + r

def _bsection(title, tickets, cap=None, full=False):
    """One bordered box-drawing table for a board section. When full=True,
    titles are shown untruncated (Title column sized to the longest shown title)
    and a horizontal separator is drawn between every ticket row."""
    if not tickets:
        return
    shown = tickets[:cap] if cap else tickets
    tw = max([len("Title")] + [len(t["title"]) for t in shown]) if full else _TITLE_DEFAULT
    w = _BW_FIXED + [tw]
    extra = f"  (showing {cap} of {len(tickets)})" if (cap and len(tickets) > cap) else ""
    print(f"\n {title}{extra}  ·  {len(tickets)}")
    print(_bborder("┌", "┬", "┐", w))
    print(_brow(["ID", "Team", "Status", "Pri", "Age", "Title"], w))
    print(_bborder("├", "┼", "┤", w))
    for idx, t in enumerate(shown):
        print(_brow([t["id"], t["team"], t["status"],
                     (t.get("priority", "med")).upper(),
                     f"{days_since(t['updated']['ts'])}d", t["title"]], w))
        if full and idx < len(shown) - 1:
            print(_bborder("├", "┼", "┤", w))
    print(_bborder("└", "┴", "┘", w))

def cmd_board(a):
    """Curated box-drawing board. Section order: ACTIVE (in_progress/blocked/open,
    priority→stale-sorted) → RECENTLY COMPLETED (done/verified, most-recent first,
    capped at --recent N=8) → BACKLOG & CANCELLED (backlog priority→newest-first,
    then cancelled). Optional --team / --epic filters."""
    try:
        recent = int(a.recent or 8)
        if recent < 0:
            raise ValueError
    except (TypeError, ValueError):
        sys.exit(f"bad --recent value {a.recent!r} (expected a non-negative integer)")
    active, backlog, completed, cancelled = [], [], [], []
    for f in sorted(TICKETS.glob("T-*.json")):
        t = json.loads(f.read_text())
        if a.team and t["team"] != a.team:
            continue
        if a.epic and t.get("epic") != a.epic:
            continue
        s = t["status"]
        if s in ("in_progress", "blocked", "open"):
            active.append(t)
        elif s == "backlog":
            backlog.append(t)
        elif s in ("done", "verified"):
            completed.append(t)
        elif s == "cancelled":
            cancelled.append(t)
    # Active: priority first, then stale-first (older untouched rises to top).
    active.sort(key=lambda t: (_PRI.get(t.get("priority"), 1), -t["updated"]["ts"]))
    # Backlog: priority first, then newest (ready-to-pick-up at top).
    backlog.sort(key=lambda t: (_PRI.get(t.get("priority"), 1), -t["updated"]["ts"]))
    # Completed: most-recently-touched first.
    completed.sort(key=lambda t: -t["updated"]["ts"])
    # Cancelled: most-recent first.
    cancelled.sort(key=lambda t: -t["updated"]["ts"])
    filt = (f" [team={a.team}]" if a.team else "") + (f" [epic={a.epic}]" if a.epic else "")
    tag = " (full)" if a.full else ""
    print(f"\n╔══ TICKET BOARD{filt}{tag} " + "═" * (95 - len(filt) - len(tag)) + "╗")
    _bsection("ACTIVE", active, full=a.full)
    _bsection("RECENTLY COMPLETED", completed, cap=recent, full=a.full)
    _bsection("BACKLOG & CANCELLED", backlog + cancelled, full=a.full)
    print(f"\n {len(active)} active · {len(completed)} done/verified · "
          f"{len(backlog)} backlog · {len(cancelled)} cancelled")

def _wrap(text, width):
    """Word-wrap text to width, returning list of lines (preserves paragraphs)."""
    out = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            if line and len(line) + 1 + len(w) > width:
                out.append(line); line = w
            else:
                line = (line + " " + w).strip()
        out.append(line)
    return out or [""]

def _fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))

def cmd_show(a):
    """Show one ticket. Pretty (box-drawing) by default; --json for raw JSON."""
    t = load(a.id)
    if a.json:
        print(json.dumps(t, indent=2)); return
    W = 86; inner = W - 4
    def box(title, body_lines):
        print()
        print("┌" + "─" * (W - 2) + "┐")
        if title:
            print("│ " + title.ljust(inner)[:inner] + " │")
            print("├" + "─" * (W - 2) + "┤")
        for ln in body_lines:
            for wln in _wrap(ln, inner):
                print("│ " + wln.ljust(inner) + " │")
        print("└" + "─" * (W - 2) + "┘")
    # Title banner
    print()
    print("╔" + "═" * (W - 2) + "╗")
    banner = f"  🎫  {t['id']}  —  {t['title']}"
    if len(banner) > W - 2:
        banner = banner[:W - 3] + "…"
    print("║" + banner.ljust(W - 2) + "║")
    print("╚" + "═" * (W - 2) + "╝")
    # Metadata
    kv = [
        f"Status: {t['status'].upper()}",
        f"Team / Assignee: {t['team']} / {t.get('assignee','-')}",
        f"Priority: {t.get('priority','med')}",
        f"Epic: {t.get('epic') or '-'}",
        f"Labels: {', '.join(t.get('labels',[])) or '-'}",
        f"Depends on: {', '.join(t.get('depends_on',[])) or '(none)'}",
        f"Blocked: {t.get('blocked_reason') or 'no'}",
        f"Created: {_fmt_ts(t['created']['ts'])}  by {t['created']['by']}",
        f"Updated: {_fmt_ts(t['updated']['ts'])}  by {t['updated']['by']}",
    ]
    box("METADATA", kv)
    # Description
    box("DESCRIPTION", [t.get("description","(none)")])
    # Acceptance criteria
    box("ACCEPTANCE CRITERIA", [t.get("acceptance_criteria","(none)")])
    # Usage (self-reported LLM usage records — no cost calc)
    usage = t.get("usage", [])
    if usage:
        ulines = []
        for u in usage:
            parts = [f"{k}={v}" for k, v in [("model", u.get("model")), ("effort", u.get("effort")),
                     ("tokens", u.get("tokens")), ("platform", u.get("platform"))] if v is not None]
            line = f"{_fmt_ts(u['ts'])}  {u.get('by','?')}  " + ", ".join(parts)
            if u.get("note"): line += f" — {u['note']}"
            ulines.append(line)
        box("USAGE (self-reported)", ulines)
    # Timeline
    comments = sorted(t.get("comments",[]), key=lambda c: c["ts"])
    body = []
    prev_date = None
    for i, c in enumerate(comments):
        date = time.strftime("%Y-%m-%d", time.gmtime(c["ts"]))
        if date != prev_date:
            if i: body.append("· · · · ·")
            body.append(f"── {date} ──"); prev_date = date
        hm = time.strftime("%H:%M", time.gmtime(c["ts"]))
        body.append(f"{hm}  {c.get('by','?')}")
        body.append("    " + c.get("text",""))
    box(f"TIMELINE  ({len(comments)} events)", body or ["(no events)"])
    print()

def cmd_status(a):
    if a.status not in STATUSES: sys.exit(f"bad status {a.status} (use {sorted(STATUSES)})")
    t = load(a.id); old = t["status"]; t["status"] = a.status
    if a.blocked_reason is not None:
        t["blocked_reason"] = None if a.blocked_reason == "-" else a.blocked_reason
    elif a.status != "blocked":
        t["blocked_reason"] = None
    t["updated"] = {"ts": now(), "by": actor()}
    t["comments"].append({"ts": now(), "by": actor(),
        "text": f"status: {old} -> {a.status}" + (f" (reason: {t['blocked_reason']})" if t.get('blocked_reason') else "")})
    add_history(t, old, a.status)
    save(t); index_refresh()
    print(f"{t['id']} status {old} -> {a.status}")

def cmd_assign(a):
    if a.team not in team_names(): sys.exit(f"bad team {a.team} (known: {sorted(team_names())})")
    t = load(a.id); old = t.get("assignee"); t["team"] = a.team; t["assignee"] = a.team
    t["updated"] = {"ts": now(), "by": actor()}
    t["comments"].append({"ts": now(), "by": actor(), "text": f"assign: {old} -> {a.team}"})
    add_history(t, old, a.team, kind="assign")
    save(t); index_refresh()
    if a.notify and a.team != old:
        notify(a.team, f"Ticket {t['id']} assigned to {a.team}: {t['title']}",
               f"Ticket {t['id']} reassigned {old} -> {a.team} by {actor()}.\nTitle: {t['title']}\nSee tmp/tickets/{t['id']}.json")
    print(f"{t['id']} assigned -> {a.team}")

def cmd_set(a):
    t = load(a.id)
    if a.title:
        t["title"] = " ".join(a.title); t["updated"] = {"ts": now(), "by": actor()}
        t["comments"].append({"ts": now(), "by": actor(), "text": f"set: title"})
    apply_fields(t, a, lambda msg: t["comments"].append({"ts": now(), "by": actor(), "text": msg}))
    save(t); index_refresh()
    print(f"updated {t['id']}")

def cmd_comment(a):
    t = load(a.id); t["comments"].append({"ts": now(), "by": actor(), "text": " ".join(a.text)})
    t["updated"] = {"ts": now(), "by": actor()}; save(t); index_refresh()
    print(f"comment added to {t['id']}")

def detect_env_usage():
    """Best-effort auto-detect of model/platform/effort from the harness's own
    env vars (set by Claude Code at session start) — no guessing, no API call.
    Returns (model, platform, effort, auto_fields) — auto_fields lists which of
    the three were filled from env vars (annotated in the note as unverified)."""
    model = platform = effort = None
    auto = []
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1":
        platform = "bedrock"; auto.append("platform")
        model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or os.environ.get("ANTHROPIC_MODEL")
        if model: auto.append("model")
    elif os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
        platform = "other"; auto.append("platform")  # vertex; PLATFORMS has no dedicated slot yet
    elif os.environ.get("ANTHROPIC_BASE_URL"):
        platform = "other"; auto.append("platform")  # custom proxy / base URL
    if not model:
        model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        if model: auto.append("model")
    effort = os.environ.get("CLAUDE_EFFORT")
    if effort: auto.append("effort")
    return model, platform, effort, auto

def cmd_usage(a):
    """Log a self-reported LLM usage record: model, effort, tokens, platform. No cost calc.
    Auto-detects model/platform/effort from harness env vars when not passed explicitly;
    auto-filled values are flagged in the note since they reflect the harness's OWN
    default config, not a verified per-request confirmation (e.g. a proxy or gateway
    can still route to a different backend than the env vars declare)."""
    env_model, env_platform, env_effort, auto = detect_env_usage()
    model = a.model or env_model
    platform = a.platform or env_platform
    effort = a.effort or env_effort
    if platform and platform not in PLATFORMS:
        sys.exit(f"bad platform {platform} (use {sorted(PLATFORMS)})")
    note = a.note
    # only flag fields that were actually filled from env (i.e. the user didn't pass them explicitly)
    auto_used = [f for f in auto if getattr(a, f) is None]
    if auto_used:
        tag = f"[auto-detected from env: {', '.join(auto_used)} — unverified, reflects harness config not confirmed per-request]"
        note = (note + " " if note else "") + tag
    t = load(a.id)
    rec = {"ts": now(), "by": actor(), "model": model, "effort": effort,
           "tokens": a.tokens, "platform": platform, "note": note}
    t.setdefault("usage", []).append(rec)
    parts = [f"{k}={v}" for k, v in [("model", a.model), ("effort", a.effort),
             ("tokens", a.tokens), ("platform", a.platform)] if v is not None]
    t["comments"].append({"ts": now(), "by": actor(), "text": "usage: " + ", ".join(parts) + (f" — {a.note}" if a.note else "")})
    t["updated"] = {"ts": now(), "by": actor()}; save(t); index_refresh()
    print(f"usage logged for {t['id']}")

def cmd_close(a):
    a.status = "done"; a.blocked_reason = None; cmd_status(a)

def cmd_verify(a):
    # Verifier gate: only the declared verifier team may set status=verified.
    # If no verifier is declared, the gate is OFF (anyone may verify) — for
    # projects that don't use a separation-of-powers QA model (e.g. marketing).
    v = verifier_team()
    if v is not None and actor() != v:
        sys.exit(f"only {v} can verify tickets (you are {actor()}); use `close` for done")
    a.status = "verified"; a.blocked_reason = None; cmd_status(a)

def cmd_reopen(a):
    # Quality fail -> back to in_progress with a required reason (recorded as a comment).
    reason = " ".join(a.reason)
    if not reason.strip(): sys.exit("reopen requires a reason")
    t = load(a.id); old = t["status"]; t["status"] = "in_progress"; t["blocked_reason"] = None
    t["updated"] = {"ts": now(), "by": actor()}
    t["comments"].append({"ts": now(), "by": actor(),
        "text": f"status: {old} -> in_progress (QA reopen: {reason})"})
    add_history(t, old, "in_progress", kind="reopen")
    save(t); index_refresh()
    print(f"{t['id']} status {old} -> in_progress (QA reopen: {reason})")

def cmd_duplicate(a):
    dup = load(a.id); orig = load(a.of_id)
    dup["status"] = "cancelled"; dup["updated"] = {"ts": now(), "by": actor()}
    dup["comments"].append({"ts": now(), "by": actor(), "text": f"duplicate of {a.of_id}; cancelled"})
    save(dup)
    orig["comments"].append({"ts": now(), "by": actor(), "text": f"duplicate reported: {a.id} (cancelled)"})
    orig["updated"] = {"ts": now(), "by": actor()}; save(orig)
    index_refresh()
    if a.archive:
        do_archive(a.id)
    print(f"{a.id} marked duplicate of {a.of_id} (cancelled)" + (" + archived" if a.archive else ""))

def do_archive(tid):
    t = load(tid)
    ym = time.strftime("%Y-%m", time.gmtime(now()))
    dest = TICKETS / "archive" / ym; dest.mkdir(parents=True, exist_ok=True)
    src = TICKETS / f"{tid}.json"
    (dest / f"{tid}.json").write_text(json.dumps(t, indent=2))
    src.unlink()
    index_refresh()
    return dest / f"{tid}.json"

def cmd_archive(a):
    if a.all_done:
        moved = []
        for f in sorted(TICKETS.glob("T-*.json")):
            t = json.loads(f.read_text())
            if t["status"] in ("verified", "cancelled"):
                do_archive(t["id"]); moved.append(t["id"])
        print(f"archived {len(moved)} verified/cancelled: {moved}")
    else:
        if not a.id: sys.exit("usage: archive <id>  |  archive --all-done")
        do_archive(a.id); print(f"archived {a.id}")

def cmd_stale(a):
    days = int(a.days or 7); found = 0
    for f in sorted(TICKETS.glob("T-*.json")):
        t = json.loads(f.read_text())
        if t["status"] in ("open", "in_progress", "blocked", "done") and days_since(t["updated"]["ts"]) >= days:
            print(f"{t['id']}  [{t['team']:8}]  {t['status']:11}  {days_since(t['updated']['ts'])}d  {t['title']}")
            found += 1
    if not found: print(f"(no tickets stale >= {days}d)")

# --- project + team management (added 2026-09-04) ---------------------------
def _valid_project_name(name):
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        sys.exit("invalid project name (letters/digits/-/_ only)")
    return name

def _atomic_write_json(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2)); tmp.replace(p)

def _project_meta(root, name):
    """Read projects/<name>/project.json if present, else None. Holds project-level metadata
    (currently: workdir — the directory where the team actually works, separate from this
    coordination store of tickets/teams/mailbox)."""
    p = root / name / "project.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except Exception: return None
    return None

def cmd_projects(a):
    """`projects` lists existing projects (+ their workdir if set); `projects create <name>
    [--workdir <path>]` makes a new one (empty tickets + mailbox + teams dirs) and, when
    --workdir is given, creates that working directory if missing and records it in
    project.json; `projects rename <old> <new>` renames one. Never touches another project.
    A project is just a directory under projects/, and nothing inside its data files references
    the project name, so a rename is a safe atomic move — but team sessions must re-export
    AGENT_TEAM_PROJECT=<new>."""
    root = pathlib.Path(os.environ.get("AGENT_TEAM_PROJECTS_ROOT")
        or str(pathlib.Path(__file__).resolve().parents[1] / "projects"))
    if a.projects_cmd == "create":
        _valid_project_name(a.name)
        base = root / a.name
        (base / "tickets").mkdir(parents=True, exist_ok=True)
        (base / "teams_mailbox").mkdir(parents=True, exist_ok=True)
        (base / "teams").mkdir(parents=True, exist_ok=True)
        wd = ""
        if getattr(a, "workdir", None):
            wd = str(pathlib.Path(a.workdir).expanduser().resolve())
            pathlib.Path(wd).mkdir(parents=True, exist_ok=True)  # create the workdir if missing
            _atomic_write_json(base / "project.json", {"name": a.name, "workdir": wd})
        print(f"project '{a.name}' ready at {base}")
        if wd:
            print(f"  workdir: {wd}  (team sessions cd here to work)")
        print(f"  join with: export AGENT_TEAM_PROJECT={a.name} CLAUDE_TEAM=<team>")
    elif a.projects_cmd == "rename":
        _valid_project_name(a.new_name)
        old = root / a.old_name
        new = root / a.new_name
        if not old.exists():
            sys.exit(f"no project named '{a.old_name}' (in {root})")
        if new.exists():
            sys.exit(f"a project named '{a.new_name}' already exists (in {root})")
        os.replace(old, new)  # atomic on the same filesystem; refuses across volumes
        print(f"renamed '{a.old_name}' → '{a.new_name}'")
        print(f"  restart the board with --project {a.new_name} (or switch in the UI)")
        print(f"  team sessions must re-export: export AGENT_TEAM_PROJECT={a.new_name}")
    else:
        if root.exists():
            names = sorted(d.name for d in root.iterdir() if d.is_dir())
            for n in names:
                wd = (_project_meta(root, n) or {}).get("workdir", "")
                print(f"{n}  ->  {wd}" if wd else n)
            if not names: print("(no projects yet)")
        else:
            print("(no projects yet)")

def cmd_teams(a):
    """`teams list` shows discovered teams + roles; `teams add`/`teams remove` edit
    the registry (requires a project). Adding the first verifier turns the gate on;
    removing the last verifier turns it off."""
    if a.teams_cmd == "add":
        save_team(a.name, a.role, a.description)
        print(f"team '{a.name}' added (role={a.role})")
    elif a.teams_cmd == "remove":
        remove_team(a.name)
        print(f"team '{a.name}' removed (existing tickets/inboxes keep their team field)")
    elif a.teams_cmd == "list":
        teams = load_teams()
        if not teams:
            print("(no teams discovered — create some with `teams add <name> --role ...`)")
            return
        v = verifier_team()
        for name, m in sorted(teams.items()):
            role = m.get("role", "worker")
            tag = "  <- verifier" if role == "verifier" else ("  <- coordinator" if role == "coordinator" else "")
            print(f"{name:16} {role}{tag}")
        if not v:
            print("(no verifier declared — verify gate is OFF; anyone may verify)")

def cmd_whoami(a):
    """Print the resolved team + which source it came from. Used by the skills to determine
    the acting team without a round-trip ask."""
    v = os.environ.get("CLAUDE_TEAM")
    if v:
        print(f"{v}\t(source: CLAUDE_TEAM env)"); return
    cf = pathlib.Path.cwd() / ".current_team"
    if cf.exists() and cf.read_text().strip():
        print(f"{cf.read_text().strip()}\t(source: {cf})"); return
    gf = pathlib.Path.home() / ".config" / "aira" / "current_team"
    if gf.exists() and gf.read_text().strip():
        print(f"{gf.read_text().strip()}\t(source: {gf})"); return
    print("unknown\t(set with: /set-team <team>, or `export CLAUDE_TEAM=<team>` before launch)")

# --- argparse ---
p = argparse.ArgumentParser()
p.add_argument("--by", default=None, help="actor (overrides CLAUDE_TEAM)")
sub = p.add_subparsers(dest="cmd", required=True)

n = sub.add_parser("new"); n.add_argument("team"); n.add_argument("title", nargs="+")
n.add_argument("--status", default=None, choices=["backlog", "open"])
n.add_argument("--no-notify", dest="notify", action="store_false")
n.add_argument("--force", action="store_true", help="override --ac requirement / unknown team")
add_field_args(n)

l = sub.add_parser("list"); l.add_argument("team", nargs="?"); l.add_argument("status", nargs="?")
l.add_argument("--label", default=None); l.add_argument("--epic", default=None)

bd = sub.add_parser("board"); bd.add_argument("--team", default=None); bd.add_argument("--epic", default=None)
bd.add_argument("--recent", default=None, help="cap completed section (default 8)")
bd.add_argument("--full", action="store_true", help="show full titles (untruncated) + row separators")

s = sub.add_parser("show"); s.add_argument("id"); s.add_argument("--json", action="store_true", help="raw JSON (default is pretty box-drawing)")

st = sub.add_parser("status"); st.add_argument("id"); st.add_argument("status"); st.add_argument("--blocked-reason", dest="blocked_reason", default=None)

asg = sub.add_parser("assign"); asg.add_argument("id"); asg.add_argument("team"); asg.add_argument("--no-notify", dest="notify", action="store_false")

se = sub.add_parser("set"); se.add_argument("id"); se.add_argument("--title", nargs="+", default=None); add_field_args(se)

c = sub.add_parser("comment"); c.add_argument("id"); c.add_argument("text", nargs="+")

us = sub.add_parser("usage"); us.add_argument("id")
us.add_argument("--model", default=None); us.add_argument("--effort", default=None,
    choices=[None, "low", "medium", "high", "xhigh", "max"])
us.add_argument("--tokens", type=int, default=None, help="estimated tokens (self-reported)")
us.add_argument("--platform", default=None, help=f"one of {sorted(PLATFORMS)}")
us.add_argument("--note", default=None)

cl = sub.add_parser("close"); cl.add_argument("id")
vf = sub.add_parser("verify"); vf.add_argument("id")
ro = sub.add_parser("reopen"); ro.add_argument("id"); ro.add_argument("reason", nargs="+")

du = sub.add_parser("duplicate"); du.add_argument("id"); du.add_argument("of_id"); du.add_argument("--archive", action="store_true")

ar = sub.add_parser("archive"); ar.add_argument("id", nargs="?"); ar.add_argument("--all-done", dest="all_done", action="store_true")

sla = sub.add_parser("stale"); sla.add_argument("days", nargs="?")

pj = sub.add_parser("projects", help="list projects, create a new project store, or rename one")
pjs = pj.add_subparsers(dest="projects_cmd", required=False)
pc = pjs.add_parser("create"); pc.add_argument("name"); pc.add_argument("--workdir", default=None,
    help="project working directory (where the team works); created if missing, recorded in project.json")
prn = pjs.add_parser("rename"); prn.add_argument("old_name"); prn.add_argument("new_name")

tm = sub.add_parser("teams", help="list/add/remove teams and their roles")
tms = tm.add_subparsers(dest="teams_cmd", required=True)
ta = tms.add_parser("add"); ta.add_argument("name")
ta.add_argument("--role", default="worker", choices=["verifier", "coordinator", "worker"])
ta.add_argument("--description", default=None)
trem = tms.add_parser("remove"); trem.add_argument("name")
tms.add_parser("list")

sub.add_parser("whoami", help="print the resolved team + source (env > .current_team > global > unknown)")

args = p.parse_args()
if args.by: os.environ["CLAUDE_TEAM"] = args.by
{"new": cmd_new, "list": cmd_list, "board": cmd_board, "show": cmd_show, "status": cmd_status, "assign": cmd_assign,
 "set": cmd_set, "comment": cmd_comment, "usage": cmd_usage, "close": cmd_close, "verify": cmd_verify,
 "reopen": cmd_reopen, "duplicate": cmd_duplicate,
 "archive": cmd_archive, "stale": cmd_stale, "projects": cmd_projects, "teams": cmd_teams,
 "whoami": cmd_whoami}[args.cmd](args)
