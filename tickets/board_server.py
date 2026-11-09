#!/usr/bin/env python3
"""Web UI for the ticket board + team mailbox. Stdlib only (no deps).

Run:  python3 tickets/board_server.py [--port 8889] [--host 127.0.0.1] [--project <name>]
Open: http://127.0.0.1:8889

Project-scoped: reads projects/<name>/{tickets,teams_mailbox} (override the root with
AGENT_TEAM_PROJECTS_ROOT). The --project flag and the in-UI project switcher select the
active project; team manager lets you add/remove teams and set roles (verifier/coordinator/
worker). Reads ticket JSONs + mailbox JSONL directly from disk; writes route through the
ticket CLI (atomic, consistent). Auto-refreshes every 30s (read-only pages).
"""
import json, os, sys, time, html, argparse, pathlib, subprocess, shlex, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, quote as urlquote, unquote as urlunquote

REPO = pathlib.Path(__file__).resolve().parents[1]  # aira repo root
PROJECT_ROOT = pathlib.Path(os.environ.get("AGENT_TEAM_PROJECTS_ROOT", str(REPO / "projects")))
DEFAULT_PROJECT = os.environ.get("AGENT_TEAM_PROJECT", "default")
TICKET_CLI = str(REPO / "tickets" / "ticket_cli.py")
MAILBOX_CLI = str(REPO / "teams_mailbox" / "mailbox_cli.py")
_ACTIVE = {"project": None}  # active project name; set by --project arg or ?project= switch

def active_project():
    return _ACTIVE["project"] or DEFAULT_PROJECT

def _cookie_project(headers):
    """Read the 'project' cookie from request headers, or None."""
    c = headers.get("Cookie")
    if not c:
        return None
    for part in c.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "project" and v:
            return urlunquote(v)
    return None

def resolve_project(qs=None, form=None, headers=None):
    """Pick the active project for THIS request, in priority order:
    query string ?project= > POST form 'project' > cookie > _ACTIVE seed > default.
    do_GET/do_POST set _ACTIVE['project'] to this so module-wide active_project()
    (used by every render + run_cli) sees the right project for this request.
    This is what makes the project per-tab sticky: every link/form carries ?project=,
    so each tab re-seeds _ACTIVE to its own project on every request, and one tab
    switching projects no longer flips the board another tab is looking at."""
    if qs is not None:
        pv = qs.get("project")
        if isinstance(pv, list):
            pv = pv[0] if pv else None
        if pv:
            return pv
    if form is not None:
        pv = form.get("project")
        if isinstance(pv, list):
            pv = pv[0] if pv else None
        if pv:
            return pv
    if headers is not None:
        cv = _cookie_project(headers)
        if cv:
            return cv
    return _ACTIVE["project"] or DEFAULT_PROJECT

def purl(path):
    """Append the active project to a link path as ?project= (or &project= if a query
    already exists), so every navigation/refresh/redirect is self-describing its project
    and the tab stays locked to it regardless of what other tabs do."""
    ap = active_project()
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}project={urlquote(ap)}"

def project_paths(project=None):
    project = project or active_project()
    base = PROJECT_ROOT / project
    return base / "tickets", base / "teams_mailbox", project

def list_projects():
    if not PROJECT_ROOT.exists(): return []
    return sorted(d.name for d in PROJECT_ROOT.iterdir() if d.is_dir())

def _project_meta_web(project):
    """Return the project's recorded workdir (where the team works) from project.json, or None."""
    p = PROJECT_ROOT / project / "project.json"
    if p.exists():
        try: return json.loads(p.read_text()).get("workdir") or None
        except Exception: return None
    return None

def load_teams_web(project=None):
    """Discover teams for a project: registry manifests, else scan tickets+inboxes
    (conventional roles: quality->verifier, supervisor->coordinator, scouting->coordinator legacy). Same logic as the CLIs."""
    project = project or active_project()
    td = PROJECT_ROOT / project / "teams"
    teams = {}
    if td.exists():
        for f in sorted(td.glob("*.json")):
            try:
                m = json.loads(f.read_text()); teams[m.get("name", f.stem)] = m
            except Exception:
                continue
    if teams:
        return teams
    tickets, mailbox, _ = project_paths(project)
    names = set()
    if tickets.exists():
        for f in tickets.glob("T-*.json"):
            try: t = json.loads(f.read_text())
            except Exception: continue
            if t.get("team"): names.add(t["team"])
    if mailbox.exists():
        for d in mailbox.glob("*/inbox.jsonl"): names.add(d.parent.name)
    conv = {"quality": "verifier", "supervisor": "coordinator", "scouting": "coordinator"}
    return {n: {"name": n, "role": conv.get(n, "worker")} for n in sorted(names)}

def team_names_web():
    return list(load_teams_web().keys())

def verifier_team_web():
    for name, m in load_teams_web().items():
        if m.get("role") == "verifier": return name
    return None

PRI = {"high": 0, "med": 1, "low": 2, None: 1}
STATUS_COLOR = {
    "blocked": "#ef4444", "in_progress": "#f59e0b", "open": "#3b82f6",
    "backlog": "#64748b", "verified": "#22c55e", "done": "#14b8a6", "cancelled": "#94a3b8",
}
PRI_COLOR = {"high": "#dc2626", "med": "#d97706", "low": "#64748b"}
STATUSES = ["backlog", "open", "in_progress", "blocked", "done", "verified", "cancelled"]
PRIORITIES = ["high", "med", "low"]
ROLES = ["worker", "coordinator", "verifier"]

def run_cli(args, cli=TICKET_CLI):
    """Run a CLI command scoped to the active project, return (rc, out, err)."""
    full = ["python3", cli] + (["--project", active_project()] if active_project() else []) + args
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def load_all():
    tickets, _, _ = project_paths()
    out = []
    if not tickets.exists(): return out
    for f in sorted(tickets.glob("T-*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            continue
    return out

def load_mailbox(team=None):
    """Load messages from one team's inbox, or all teams."""
    _, mailbox, _ = project_paths()
    msgs = []
    teams = [team] if team else team_names_web()
    for t in teams:
        mb = mailbox / t / "inbox.jsonl"
        if not mb.exists():
            continue
        for line in mb.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
                m["_team"] = t  # which inbox this is in
                msgs.append(m)
            except json.JSONDecodeError:
                continue
    msgs.sort(key=lambda m: m.get("ts", 0), reverse=True)
    return msgs

def u_ts(t, default=0):
    """Defensive accessor for a ticket's updated.ts — some legacy/hand-edited tickets store
    `updated` as a string. Degrade to `default` so one bad ticket can't crash the board."""
    u = t.get("updated")
    if isinstance(u, dict) and isinstance(u.get("ts"), (int, float)):
        return u["ts"]
    return default

def u_by(t, default="?"):
    u = t.get("updated")
    return u["by"] if isinstance(u, dict) and u.get("by") else default

def age(t):
    return (int(time.time()) - u_ts(t)) // 86400

def esc(s):
    return html.escape(str(s or ""))

def md(text):
    """Minimal markdown -> HTML for ticket descriptions/AC (stdlib only).
    Supports: tables, headings (#..###), bold (**x**), italics (*x*),
    inline code (`x`), unordered lists (- ), ordered lists (1. ), and
    paragraphs. Escapes HTML first, so content can't inject markup.
    Lines are handled in order; a table is a contiguous run of | rows."""
    if not text:
        return ""
    s = html.escape(str(text))
    lines = s.split("\n")
    out = []
    i = 0
    n = len(lines)
    def inline(t):
        # inline code first (so its contents aren't further processed)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        # bold
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        # italics (single * not adjacent to word chars)
        t = re.sub(r"(?<![*\w])\*([^\*\n]+)\*(?![*\w])", r"<em>\1</em>", t)
        return t
    while i < n:
        ln = lines[i]
        stripped = ln.strip()
        # table: a run of rows starting with |
        if stripped.startswith("|"):
            tbl = ["<table class='mdtable'><tbody>"]
            while i < n and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                cells = [c.strip() for c in row.strip("|").split("|")]
                # skip separator rows like |---|---|
                if all(re.match(r"^:?-+:?$|^$", c) for c in cells):
                    i += 1; continue
                tbl.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            tbl.append("</tbody></table>")
            out.append("".join(tbl)); continue
        # headings
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl+3}>{inline(m.group(2))}</h{lvl+3}>")  # h4..h6, page already has h1-h3
            i += 1; continue
        # unordered list
        if re.match(r"^[-*]\s+", stripped):
            items = []
            ulpfx = re.compile(r"^[-*]\s+")
            while i < n and ulpfx.match(lines[i].strip()):
                items.append(f"<li>{inline(ulpfx.sub('', lines[i].strip()))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        # ordered list
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            olpfx = re.compile(r"^\d+\.\s+")
            while i < n and olpfx.match(lines[i].strip()):
                items.append(f"<li>{inline(olpfx.sub('', lines[i].strip()))}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>"); continue
        # blank line
        if not stripped:
            out.append("")  # paragraph break
            i += 1; continue
        # paragraph (accumulate consecutive non-blank, non-special lines)
        para = [stripped]
        i += 1
        while i < n and lines[i].strip() and not lines[i].strip().startswith("|") \
              and not re.match(r"^(#{1,3}\s|[-*]\s|\d+\.\s)", lines[i].strip()):
            para.append(lines[i].strip()); i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    # collapse empty <p></p> from blank lines
    return re.sub(r"<p>\s*</p>", "", "\n".join(out))

def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else "-"

def cell(s, cls=""):
    return f'<td class="{cls}">{esc(s)}</td>'

def to_list(m):
    to = m.get("to")
    if isinstance(to, list):
        return to
    if isinstance(to, str):
        return [x.strip() for x in to.split(",")]
    return []

def base_url(qs):
    """Rebuild a board URL preserving filters from a query dict."""
    p = []
    for k in ["status", "team", "epic", "priority"]:
        v = qs.get(k)
        if v and v != "all" and v != ["all"]:
            if isinstance(v, list): v = v[0]
            p.append(f"{k}={esc(v)}")
    return "/?" + "&".join(p) if p else "/"

def filter_tickets(tickets, qs):
    """Apply status/team/epic/priority filters from query string."""
    def g(k):
        v = qs.get(k)
        if isinstance(v, list): v = v[0] if v else None
        return v
    f_status, f_team, f_epic, f_pri = g("status"), g("team"), g("epic"), g("priority")
    out = []
    for t in tickets:
        if f_status and f_status != "all" and t.get("status") != f_status: continue
        if f_team and f_team != "all" and t.get("team") != f_team: continue
        if f_epic and f_epic != "all" and t.get("epic") != f_epic: continue
        if f_pri and f_pri != "all" and (t.get("priority") or "med") != f_pri: continue
        out.append(t)
    return out

def render_filter_bar(qs, tickets):
    """Render the filter dropdowns + epic list."""
    def sel(k, val):
        v = qs.get(k)
        if isinstance(v, list): v = v[0] if v else None
        return "selected" if v == val else ""
    epics = sorted({t.get("epic") for t in tickets if t.get("epic")})
    h = '<div class="filters"><form method="get" action="/">'
    h += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    h += '<select name="status" onchange="this.form.submit()"><option value="all">All status</option>'
    for s in STATUSES:
        h += f'<option value="{s}" {sel("status",s)}>{s}</option>'
    h += '</select> <select name="team" onchange="this.form.submit()"><option value="all">All teams</option>'
    for t in team_names_web():
        h += f'<option value="{t}" {sel("team",t)}>{t}</option>'
    h += '</select> <select name="epic" onchange="this.form.submit()"><option value="all">All epics</option>'
    for e in epics:
        h += f'<option value="{esc(e)}" {sel("epic",e)}>{esc(e)}</option>'
    h += '</select> <select name="priority" onchange="this.form.submit()"><option value="all">All priority</option>'
    for p in PRIORITIES:
        h += f'<option value="{p}" {sel("priority",p)}>{p}</option>'
    h += '</select> <select name="recent" onchange="this.form.submit()">'
    rv = qs.get("recent")
    if isinstance(rv, list): rv = rv[0] if rv else None
    for val, label in (("8", "8 per page"), ("20", "20 per page"), ("50", "50 per page"), ("999", "All")):
        h += f'<option value="{val}" {"selected" if (rv or "8") == val else ""}>{label}</option>'
    h += f'</select> <a href="{purl("/")}" class="clear">clear</a></form></div>'
    return h

def nav(active="board"):
    """Top nav: Board / Inbox / Teams + a project switcher dropdown. Selecting a
    project submits GET /?project=<name>, which do_GET applies before rendering."""
    ap = active_project()
    def cls(name): return 'class="active"' if active == name else ''
    links = (f'<a href="{purl("/")}" {cls("board")}>🎫 Board</a>'
             f' <a href="{purl("/inbox")}" {cls("inbox")}>📬 Inbox</a>'
             f' <a href="{purl("/teams")}" {cls("teams")}>👥 Teams</a>')
    projs = list_projects()
    opts = "".join(f'<option value="{esc(p)}" {"selected" if p==ap else ""}>{esc(p)}</option>' for p in projs)
    if ap and ap not in projs:
        opts += f'<option value="{esc(ap)}" selected>{esc(ap)}</option>'
    if not projs and not ap:
        opts = '<option value="">(none)</option>'
    # the switcher is the one place the project changes intentionally: it submits ?project=<name>
    switcher = (f'<form method="get" action="/" style="display:inline;margin-left:14px">'
                f'<select name="project" onchange="this.form.submit()" class="navselect">{opts}</select></form>')
    newproj = (f'<a href="{purl("/new-project")}" class="newproj">+ new project</a>')
    help_link = f'<a href="{purl("/help")}" class="help">❓ Help</a>'
    return f'<div class="nav">{links} {help_link}{switcher} <span class="projlabel">project: <b>{esc(ap)}</b></span> {newproj}</div>'

def render_board(qs):
    all_t = load_all()
    t = filter_tickets(all_t, qs)
    active, backlog, done, cancelled = [], [], [], []
    for x in t:
        s = x["status"]
        if s in ("in_progress", "blocked", "open"): active.append(x)
        elif s == "backlog": backlog.append(x)
        elif s in ("done", "verified"): done.append(x)
        elif s == "cancelled": cancelled.append(x)
    active.sort(key=lambda x: (PRI.get(x.get("priority"), 1), -u_ts(x)))
    backlog.sort(key=lambda x: (PRI.get(x.get("priority"), 1), -u_ts(x)))
    done.sort(key=lambda x: -u_ts(x))
    cancelled.sort(key=lambda x: -u_ts(x))

    # optional column sorting (sort + dir query params; applies to every section)
    SORT_COLS = {
        "id": lambda x: x["id"],
        "team": lambda x: x["team"],
        "status": lambda x: x["status"],
        "priority": lambda x: PRI.get(x.get("priority"), 1),
        "age": lambda x: u_ts(x),
        "epic": lambda x: (x.get("epic") or ""),
        "title": lambda x: (x["title"] or "").lower(),
    }
    sv = qs.get("sort")
    if isinstance(sv, list): sv = sv[0] if sv else None
    dv = qs.get("dir")
    if isinstance(dv, list): dv = dv[0] if dv else None
    sort_col = sv if sv in SORT_COLS else None
    sort_dir = dv if dv in ("asc", "desc") else "asc"
    if sort_col:
        for lst in (active, backlog, done, cancelled):
            lst.sort(key=SORT_COLS[sort_col], reverse=(sort_dir == "desc"))

    def sort_url(col):
        params = {k: (v[0] if isinstance(v, list) and v else v)
                  for k, v in qs.items() if k not in ("sort", "dir", "page")}
        params["sort"] = col
        params["dir"] = "desc" if (sort_col == col and sort_dir == "asc") else "asc"
        return "/?" + "&".join(f"{k}={urlquote(str(v))}" for k, v in params.items())

    def section(title, rows, cap=None, count_note=""):
        if not rows:
            return ""
        shown = rows[:cap] if cap else rows
        extra = (f' <span class="cap">{count_note}</span>' if count_note else
                 (f' <span class="cap">({cap} of {len(rows)})</span>' if (cap and len(rows) > cap) else ""))
        h = f'<h2>{title} <span class="count">{len(rows)}</span>{extra}</h2>'
        cols = (("ID", "id"), ("Team", "team"), ("Status", "status"), ("Pri", "priority"),
                ("Age", "age"), ("Epic", "epic"), ("Title", "title"))
        ths = []
        for label, col in cols:
            arrow, cls = "", ""
            if sort_col == col:
                arrow = " ▲" if sort_dir == "asc" else " ▼"
                cls = ' class="sorted"'
            ths.append(f'<th{cls}><a href="{sort_url(col)}">{label}{arrow}</a></th>')
        h += '<table><thead><tr>' + "".join(ths) + '<th></th></tr></thead><tbody>'
        for x in shown:
            sc = STATUS_COLOR.get(x["status"], "#333")
            pc = PRI_COLOR.get(x.get("priority", "med"), "#333")
            h += (f'<tr><td class="id"><a href="{purl("/ticket/" + x["id"])}">{esc(x["id"])}</a></td>'
                  f'<td>{esc(x["team"])}</td>'
                  f'<td><span class="badge" style="background:{sc}">{esc(x["status"])}</span></td>'
                  f'<td><span class="badge" style="background:{pc}">{esc((x.get("priority","med") or "med")).upper()}</span></td>'
                  f'<td class="age">{age(x)}d</td>'
                  f'<td class="epic">{esc(x.get("epic") or "-")}</td>'
                  f'<td class="title">{esc(x["title"])}</td>'
                  f'<td><a href="{purl("/edit/" + x["id"])}" class="editbtn">edit</a></td></tr>')
        h += '</tbody></table>'
        return h

    body = nav("board")
    body += f'<h1>🎫 Ticket Board</h1><div class="meta">auto-refresh 30s · <span class="time">{time.strftime("%H:%M:%S")}</span> · {len(t)} shown of {len(all_t)} total</div>'
    body += render_filter_bar(qs, all_t)
    body += section("ACTIVE", active)
    rv = qs.get("recent")
    if isinstance(rv, list): rv = rv[0] if rv else None
    try:
        recent = max(1, int(rv)) if rv else 8
    except (TypeError, ValueError):
        recent = 8
    # paginate the completed section; `recent` acts as pg size (999 = all)
    total = len(done)
    size = total if recent >= 999 else recent
    total_pages = max(1, -(-total // size)) if size else 1
    pv = qs.get("page")
    if isinstance(pv, list): pv = pv[0] if pv else None
    try:
        pg = max(1, min(int(pv), total_pages)) if pv else 1
    except (TypeError, ValueError):
        pg = 1
    start = (pg - 1) * size
    shown = done[start:start + size] if size else done
    note = f'({start + 1}–{start + len(shown)} of {total})' if total > size else ''
    body += section("RECENTLY COMPLETED", shown, count_note=note)
    if total_pages > 1:
        base = {k: (v[0] if isinstance(v, list) and v else v) for k, v in qs.items() if k != "page"}
        def page_url(p):
            params = dict(base)
            params["page"] = str(p)
            return "/?" + "&".join(f"{k}={urlquote(str(v))}" for k, v in params.items())
        pager_nav = []
        if pg > 1:
            pager_nav.append(f'<a href="{page_url(1)}">&laquo; first</a>')
            pager_nav.append(f'<a href="{page_url(pg - 1)}">&lsaquo; prev</a>')
        pager_nav.append(f'page {pg} of {total_pages}')
        if pg < total_pages:
            pager_nav.append(f'<a href="{page_url(pg + 1)}">next &rsaquo;</a>')
            pager_nav.append(f'<a href="{page_url(total_pages)}">last &raquo;</a>')
        # inline per-page dropdown (preserves filters + sort; resets to page 1)
        cur = "999" if recent >= 999 else str(recent)
        hidden = ""
        for k in ("status", "team", "epic", "priority", "sort", "dir"):
            v = qs.get(k)
            if isinstance(v, list): v = v[0] if v else None
            if v and v != "all":
                hidden += f'<input type="hidden" name="{k}" value="{esc(v)}">'
        hidden += f'<input type="hidden" name="project" value="{esc(active_project())}">'
        selsel = "".join(f'<option value="{v}" {"selected" if cur == v else ""}>{l}</option>'
                         for v, l in (("8", "8 per page"), ("20", "20 per page"),
                                      ("50", "50 per page"), ("999", "All")))
        pager = (f'<form method="get" action="/" style="display:inline">{hidden}'
                 f'<select name="recent" onchange="this.form.submit()">{selsel}</select></form>')
        body += f'<div style="margin:6px 0 18px;font-size:13px">{" &middot; ".join(pager_nav)} &nbsp; {pager}</div>'
    body += section("BACKLOG & CANCELLED", backlog + cancelled)
    body += f'<div class="footer">{len(active)} active · {len(done)} done/verified · {len(backlog)} backlog · {len(cancelled)} cancelled</div>'
    return page(body, refresh=True)

def render_inbox(qs):
    team = qs.get("team", ["all"])
    if isinstance(team, list): team = team[0]
    msgs = load_mailbox(None if team == "all" else team)
    body = nav("inbox")
    body += f'<h1>📬 Team Mailbox</h1><div class="meta">auto-refresh 30s · {len(msgs)} messages</div>'
    body += '<div class="filters"><form method="get" action="/inbox">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += '<select name="team" onchange="this.form.submit()"><option value="all">All teams</option>'
    for t in team_names_web():
        body += f'<option value="{t}" {"selected" if team==t else ""}>{t}</option>'
    body += '</select></form></div>'
    if not msgs:
        body += '<p class="empty">No messages.</p>'
    else:
        body += '<div class="mailbox">'
        for m in msgs:
            unread = "" if m.get("read") else "unread"
            to = ", ".join(to_list(m))
            subj = m.get("subject") or "(no subject)"
            preview = (m.get("body","") or "")[:160].replace("\n"," ")
            href = purl("/mail/" + urlquote(str(m.get('_team',''))) + "/" + urlquote(str(m.get('id',''))))
            body += (f'<a class="mail {unread}" href="{esc(href)}"><div class="mailhdr">'
                     f'<span class="mailfrom">{esc(m.get("from","?"))}</span> → '
                     f'<span class="mailto">[{esc(to)}]</span> '
                     f'<span class="mailteam">({esc(m.get("_team","?"))} inbox)</span>'
                     f'<span class="mailsub">{esc(subj)}</span>'
                     f'<span class="mailts">{esc(fmt_ts(m.get("ts")))}</span></div>'
                     f'<div class="mailprev">{esc(preview)}{"…" if len(m.get("body",""))>160 else ""}</div></a>')
        body += '</div>'
    return page(body, refresh=True)


def render_mail(team, mid):
    """Full single-message view. Read-only: never flips the read flag
    (teams' unread counts drive their workflows)."""
    if team not in load_teams_web():
        return page(f'<h1>Bad mailbox</h1><p>No mailbox for {esc(team)}.</p><p><a href="{purl("/inbox")}">← inbox</a></p>')
    for m in load_mailbox(team):
        if m.get("id") == mid:
            break
    else:
        return page(f'<h1>Not found</h1><p>Message {esc(mid)} not in {esc(team)} inbox.</p><p><a href="{purl("/inbox")}">← inbox</a></p>')
    to = ", ".join(to_list(m))
    badge = ('<span class="badge" style="background:#f59e0b">unread</span>' if not m.get("read")
             else '<span class="badge" style="background:#64748b">read</span>')
    body = f'<div class="back"><a href="{purl("/inbox")}">← inbox</a></div>'
    body += f'<h1>📬 {esc(m.get("subject") or "(no subject)")}</h1>'
    body += (f'<div class="meta">{esc(m.get("from","?"))} → [{esc(to)}] · '
             f'in {esc(team)} inbox · {esc(fmt_ts(m.get("ts")))} · {badge}'
             f'{" · in-reply-to " + esc(m["reply_to"]) if m.get("reply_to") else ""}</div>')
    body += f'<div class="mailbody">{md(m.get("body",""))}</div>'
    return page(body)

def render_ticket(tid):
    tickets, _, _ = project_paths()
    p = tickets / f"{tid}.json"
    if not p.exists():
        return page(f'<h1>Not found</h1><p>Ticket {esc(tid)} does not exist.</p><p><a href="{purl("/")}">← board</a></p>')
    t = json.loads(p.read_text())
    sc = STATUS_COLOR.get(t["status"], "#333")
    pc = PRI_COLOR.get(t.get("priority", "med"), "#333")
    body = f'<div class="back"><a href="{purl("/")}">← board</a></div>'
    body += f'<h1>🎫 {esc(t["id"])} — {esc(t["title"])}</h1>'
    kv = [
        ("Status", f'<span class="badge" style="background:{sc}">{esc(t["status"])}</span>'),
        ("Team / Assignee", f'{esc(t["team"])} / {esc(t.get("assignee","-"))}'),
        ("Priority", f'<span class="badge" style="background:{pc}">{esc((t.get("priority","med"))).upper()}</span>'),
        ("Epic", esc(t.get("epic") or "-")),
        ("Labels", esc(", ".join(t.get("labels", [])) or "-")),
        ("Depends on", esc(", ".join(t.get("depends_on", [])) or "(none)")),
        ("Blocked", esc(t.get("blocked_reason") or "no")),
        ("Created", f'{fmt_ts(t["created"]["ts"])} by {esc(t["created"]["by"])}'),
        ("Updated", f'{fmt_ts(u_ts(t))} by {esc(u_by(t))}'),
    ]
    body += '<table class="kv"><tbody>'
    for k, v in kv:
        body += f'<tr><th>{esc(k)}</th><td>{v}</td></tr>'
    body += '</tbody></table>'
    body += f'<p><a href="{purl("/edit/" + tid)}" class="editbtn">✏️ Edit this ticket</a></p>'
    body += f'<h3>Description</h3><div class="box md">{md(t.get("description","(none)"))}</div>'
    body += f'<h3>Acceptance Criteria</h3><div class="box md">{md(t.get("acceptance_criteria","(none)"))}</div>'
    usage = t.get("usage", [])
    if usage:
        body += f'<h3>Usage (self-reported, {len(usage)})</h3><table class="kv"><tbody>'
        for u in usage:
            parts = [f"{k}={esc(v)}" for k, v in [("model", u.get("model")), ("effort", u.get("effort")),
                     ("tokens", u.get("tokens")), ("platform", u.get("platform"))] if v is not None]
            row = ", ".join(parts) + (f' — {esc(u["note"])}' if u.get("note") else "")
            body += f'<tr><th>{esc(fmt_ts(u.get("ts")))}<br><span style="color:#64748b;font-weight:400">{esc(u.get("by","?"))}</span></th><td>{row}</td></tr>'
        body += '</tbody></table>'
    body += f'<h3>Timeline ({len(t.get("comments",[]))} events)</h3>'
    body += '<div class="timeline">'
    prev_date = None
    for i, c in enumerate(sorted(t.get("comments", []), key=lambda c: c["ts"])):
        d = time.strftime("%Y-%m-%d", time.gmtime(c["ts"]))
        if d != prev_date:
            if i: body += '<div class="date-sep">· · ·</div>'
            body += f'<div class="date">── {esc(d)} ──</div>'
            prev_date = d
        hm = time.strftime("%H:%M", time.gmtime(c["ts"]))
        body += f'<div class="event"><span class="ts">{esc(hm)}</span> <span class="by">{esc(c.get("by","?"))}</span><div class="text md">{md(c.get("text",""))}</div></div>'
    body += '</div>'
    return page(body)

def render_edit(tid, qs):
    tickets, _, _ = project_paths()
    p = tickets / f"{tid}.json"
    if not p.exists():
        return page(f'<h1>Not found</h1><p>Ticket {esc(tid)} does not exist.</p><p><a href="{purl("/")}">← board</a></p>')
    t = json.loads(p.read_text())
    flash = ""
    if qs.get("msg"):
        m = qs.get("msg")
        if isinstance(m, list): m = m[0]
        flash = f'<div class="flash {esc(qs.get("kind",[""])[0] if isinstance(qs.get("kind"),list) else qs.get("kind",""))}">{esc(m)}</div>'
    cur_status = t.get("status", "")
    cur_pri = t.get("priority", "med") or "med"
    body = f'<div class="back"><a href="{purl("/ticket/" + tid)}">← ticket</a></div>'
    body += f'<h1>✏️ Edit {esc(tid)}</h1>'
    body += f'<div class="meta">{esc(t["title"])}</div>'
    body += flash
    # status form
    body += '<form method="post" action="/save" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += f'<input type="hidden" name="id" value="{esc(tid)}"><input type="hidden" name="field" value="status">'
    body += '<label>Status <select name="value">'
    for s in STATUSES:
        body += f'<option value="{s}" {"selected" if s==cur_status else ""}>{s}</option>'
    body += '</select></label>'
    body += '<button type="submit">Update status</button></form>'
    # priority form
    body += '<form method="post" action="/save" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += f'<input type="hidden" name="id" value="{esc(tid)}"><input type="hidden" name="field" value="priority">'
    body += '<label>Priority <select name="value">'
    for p in PRIORITIES:
        body += f'<option value="{p}" {"selected" if p==cur_pri else ""}>{p}</option>'
    body += '</select></label>'
    body += '<button type="submit">Update priority</button></form>'
    # title form
    body += '<form method="post" action="/save" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += f'<input type="hidden" name="id" value="{esc(tid)}"><input type="hidden" name="field" value="title">'
    body += f'<label>Title <input type="text" name="value" value="{esc(t.get("title",""))}" style="width:60%"></label>'
    body += '<button type="submit">Update title</button></form>'
    body += '<p class="hint">Status/priority/title edits go through the ticket CLI (atomic + recorded as comments). For description/AC/labels/epic, use the CLI directly.</p>'
    return page(body, refresh=False)

def handle_save(form):
    tid = form.get("id", [""])[0]
    field = form.get("field", [""])[0]
    val = form.get("value", [""])[0]
    if not tid or not field:
        return page(f'<h1>Error</h1><p>Missing id or field.</p><p><a href="{purl("/")}">← board</a></p>')
    # edits made through the UI are by the human user (not the supervisor agent),
    # so the timeline distinguishes human actions from agent-automated ones
    by = "user"
    args = ["--by", by]
    if field == "status":
        args += ["status", tid, val]
    elif field == "priority":
        args += ["set", tid, "--priority", val]
    elif field == "title":
        args += ["set", tid, "--title", val]
    else:
        return page(f'<h1>Error</h1><p>Unknown field: {esc(field)}</p>')
    rc, out, err = run_cli(args)  # run_cli prepends python3 + TICKET_CLI + --project <active>
    kind = "ok" if rc == 0 else "err"
    msg = out if rc == 0 else (err or out or f"exit {rc}")
    # redirect to edit page with flash message (purl appends &project= so the tab stays locked)
    return redirect(purl(f"/edit/{tid}?msg={urlquote(msg[:300])}&kind={kind}"))

def render_team_manager(qs):
    """List teams + roles for the active project, with add/remove forms. The verifier
    role is the only one the verify gate honors; coordinator is informational."""
    teams = load_teams_web()
    v = verifier_team_web()
    flash = ""
    if qs.get("msg"):
        m = qs.get("msg")
        if isinstance(m, list): m = m[0]
        kind = qs.get("kind")
        if isinstance(kind, list): kind = kind[0] if kind else ""
        flash = f'<div class="flash {esc(kind or "")}">{esc(m)}</div>'
    body = nav("teams")
    body += f'<h1>👥 Teams — project <code>{esc(active_project())}</code></h1>'
    body += f'<div class="meta">{"verifier gate ON (only <b>" + esc(v) + "</b> can verify)" if v else "verifier gate OFF (no verifier declared — anyone may verify)"}</div>'
    body += flash
    # add form
    body += '<form method="post" action="/team-add" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += '<label>Team <input type="text" name="name" placeholder="e.g. qa, editor, security-reviewer" style="width:200px"></label>'
    body += '<label>Role <select name="role">'
    for r in ROLES:
        body += f'<option value="{r}" {"selected" if r=="worker" else ""}>{r}</option>'
    body += '</select></label>'
    body += '<label>Description <input type="text" name="description" placeholder="(optional)" style="width:260px"></label>'
    body += '<button type="submit">Add team</button></form>'
    # roster table
    if not teams:
        body += '<p class="empty">No teams yet. Add one above, or it will be auto-discovered from tickets/inboxes once they exist.</p>'
    else:
        body += '<table><thead><tr><th>Team</th><th>Role</th><th>Description</th><th></th></tr></thead><tbody>'
        for name, m in sorted(teams.items()):
            role = m.get("role", "worker")
            body += (f'<tr><td class="id">{esc(name)}</td>'
                     f'<td><span class="role {esc(role)}">{esc(role)}</span></td>'
                     f'<td>{esc(m.get("description") or "-")}</td>'
                     f'<td><form method="post" action="/team-remove" style="display:inline">'
                     f'<input type="hidden" name="project" value="{esc(active_project())}">'
                     f'<input type="hidden" name="name" value="{esc(name)}">'
                     f'<button type="submit" class="tier">remove</button></form></td></tr>')
        body += '</tbody></table>'
    # rename project (renames the active project's directory; nothing inside references the name)
    body += '<h2>Rename project</h2>'
    body += f'<form method="post" action="/rename-project" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += f'<label>New name <input type="text" name="new_name" placeholder="{esc(active_project())}" style="width:200px"></label>'
    body += f'<button type="submit">Rename {esc(active_project())}</button></form>'
    body += '<p class="hint">Renames the project directory. Team sessions must re-export <code>AGENT_TEAM_PROJECT=&lt;new&gt;</code>; switch to the new name in the dropdown (or restart the board).</p>'
    body += '<p class="hint">Removing a team deletes its registry manifest only; existing tickets/inboxes keep their team field. The verify gate turns on when exactly a verifier exists, and off when none does.</p>'
    return page(body, refresh=False)

def render_new_project(qs):
    body = nav("board")
    body += '<h1>+ New project</h1>'
    body += '<div class="meta">Creates an empty board + empty inboxes + empty team registry under projects/&lt;name&gt;/. Nothing in other projects is touched.</div>'
    flash = ""
    if qs.get("msg"):
        m = qs.get("msg")
        if isinstance(m, list): m = m[0]
        kind = qs.get("kind")
        if isinstance(kind, list): kind = kind[0] if kind else ""
        flash = f'<div class="flash {esc(kind or "")}">{esc(m)}</div>'
    body += flash
    body += '<form method="post" action="/create-project" class="editform">'
    body += f'<input type="hidden" name="project" value="{esc(active_project())}">'
    body += '<label>Project name <input type="text" name="name" placeholder="e.g. marketing, security-audit" style="width:240px"></label>'
    body += '<button type="submit">Create &amp; switch to it</button></form>'
    body += '<p class="hint">After creating, use the Teams page to add teams and roles, then point Claude sessions at it: <code>export AGENT_TEAM_PROJECT=&lt;name&gt; CLAUDE_TEAM=&lt;team&gt;</code>.</p>'
    return page(body, refresh=False)

def handle_team_add(form):
    name = (form.get("name", [""])[0] or "").strip()
    role = form.get("role", ["worker"])[0]
    desc = (form.get("description", [""])[0] or "").strip() or None
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return redirect(purl("/teams?msg=" + urlquote("invalid team name (letters/digits/-/_ only)") + "&kind=err"))
    if role not in ROLES:
        return redirect(purl("/teams?msg=" + urlquote("invalid role") + "&kind=err"))
    args = ["teams", "add", name, "--role", role]
    if desc: args += ["--description", desc]
    rc, out, err = run_cli(args)
    kind = "ok" if rc == 0 else "err"
    msg = out if rc == 0 else (err or out or f"exit {rc}")
    return redirect(purl("/teams?msg=" + urlquote(msg[:300]) + "&kind=" + kind))

def handle_team_remove(form):
    name = (form.get("name", [""])[0] or "").strip()
    if not name:
        return redirect(purl("/teams?msg=" + urlquote("missing team name") + "&kind=err"))
    rc, out, err = run_cli(["teams", "remove", name])
    kind = "ok" if rc == 0 else "err"
    msg = out if rc == 0 else (err or out or f"exit {rc}")
    return redirect(purl("/teams?msg=" + urlquote(msg[:300]) + "&kind=" + kind))

def handle_create_project(form):
    name = (form.get("name", [""])[0] or "").strip()
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return redirect(purl("/new-project?msg=" + urlquote("invalid project name (letters/digits/-/_ only)") + "&kind=err"))
    rc, out, err = run_cli(["projects", "create", name])
    if rc == 0:
        _ACTIVE["project"] = name  # switch to the new project; purl below stamps ?project=<name>
        return redirect(purl("/?msg=" + urlquote(f"created and switched to project '{name}'") + "&kind=ok"))
    return redirect(purl("/new-project?msg=" + urlquote((err or out or f"exit {rc}")[:300]) + "&kind=err"))

def handle_rename_project(form):
    """Rename the active project's directory via the CLI, then switch to the new name.
    Safe because no data inside a project references the project name (it's just the dir)."""
    old = (form.get("project", [""])[0] or "").strip()
    new = (form.get("new_name", [""])[0] or "").strip()
    if not old:
        return redirect(purl("/teams?msg=" + urlquote("missing current project") + "&kind=err"))
    if new == old:
        return redirect(purl("/teams?msg=" + urlquote("new name is the same as the current name") + "&kind=err"))
    if not new or not new.replace("-", "").replace("_", "").isalnum():
        return redirect(purl("/teams?msg=" + urlquote("invalid project name (letters/digits/-/_ only)") + "&kind=err"))
    rc, out, err = run_cli(["projects", "rename", old, new])
    if rc == 0:
        _ACTIVE["project"] = new  # switch to the renamed project
        return redirect(purl("/?msg=" + urlquote(f"renamed '{old}' → '{new}'") + "&kind=ok"))
    return redirect(purl("/teams?msg=" + urlquote((err or out or f"exit {rc}")[:300]) + "&kind=err"))

def redirect(location):
    return ("__REDIRECT__", location)

def render_help():
    """A minimal human-facing quick reference: just the slash commands + the active project/gate."""
    v = verifier_team_web()
    gate = f"ON — only <b>{esc(v)}</b> may verify" if v else "OFF (no verifier declared)"
    body = nav("help")
    body += "<h1>❓ Help — slash commands</h1>"
    body += f'<div class="meta">project: <b>{esc(active_project())}</b> · verify gate: {gate}</div>'
    wd = _project_meta_web(active_project())
    if wd:
        body += f'<div class="meta">workdir: <code>{esc(wd)}</code> — team sessions cd here to work</div>'
    body += "<table class='kv'><tbody>"
    skills = [
        ("/team-up", "spin up or connect to a project; propose a roster; start the board"),
        ("/set-team <team>", "set this session's team"),
        ("/check-inbox", "read and handle unread mail; reply-all to the audience"),
        ("/ticket <id>", "work a ticket: pickup, do via subagent, close with a checksum"),
        ("/team-send <recipients|all> <message>", "send a message (each recipient sees the full to-list)"),
        ("/lead", "coordinator pass: nudge stalled teams, roll up to the human"),
    ]
    for cmd, desc in skills:
        body += f'<tr><th><code>{esc(cmd)}</code></th><td>{desc}</td></tr>'
    body += "</tbody></table>"
    body += "<p class='hint'>Full CLI reference and rules: <code>BUILD_PROMPT.md</code> and <code>templates/README_GOVERNANCE.md</code>.</p>"
    return page(body, refresh=False)

def page(body, refresh=True):
    head = '<meta charset="utf-8">'
    if refresh:
        head += '<meta http-equiv="refresh" content="30">'
    head += '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ticket Board</title>'
    return f"""<!DOCTYPE html><html><head>{head}<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f1f5f9; color: #1e293b; max-width: 1300px; margin: 0 auto; }}
h1 {{ margin: 0 0 4px; font-size: 22px; }}
h2 {{ font-size: 15px; margin: 24px 0 8px; color: #334155; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; }}
h3 {{ font-size: 14px; margin: 20px 0 6px; color: #334155; }}
.meta {{ font-size: 12px; color: #64748b; margin-bottom: 12px; }}
.time {{ font-family: monospace; }}
.nav {{ margin-bottom: 16px; }}
.nav a {{ color: #2563eb; text-decoration: none; font-size: 15px; margin-right: 18px; padding-bottom: 3px; }}
.nav a.active {{ border-bottom: 2px solid #2563eb; font-weight: 600; }}
.navselect {{ padding: 3px 8px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 13px; background: #fff; }}
.projlabel {{ color: #64748b; font-size: 12px; margin-left: 4px; }}
.newproj {{ color: #22c55e; font-size: 12px; text-decoration: none; margin-left: 10px; }}
.help {{ color: #64748b; font-size: 13px; text-decoration: none; }}
.role {{ color: #fff; padding: 2px 7px; border-radius: 3px; font-size: 11px; font-weight: 600; display: inline-block; }}
.role.verifier {{ background: #22c55e; }} .role.coordinator {{ background: #7c3aed; }} .role.worker {{ background: #94a3b8; }}
.tier {{ color: #ef4444; font-size: 12px; text-decoration: none; margin-left: 8px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 4px; overflow: hidden; font-size: 13px; }}
th {{ background: #334155; color: #fff; text-align: left; padding: 7px 10px; font-weight: 600; font-size: 12px; }}
th a {{ color: #fff; text-decoration: none; }}
th a:hover {{ text-decoration: underline; }}
th.sorted {{ background: #2563eb; }}
td {{ padding: 7px 10px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
tr:hover td {{ background: #f8fafc; }}
.id {{ font-family: monospace; white-space: nowrap; }}
.id a {{ color: #2563eb; text-decoration: none; }}
.id a:hover {{ text-decoration: underline; }}
.age {{ color: #64748b; text-align: center; white-space: nowrap; }}
.epic {{ font-family: monospace; font-size: 11px; color: #64748b; white-space: nowrap; }}
.title {{ word-break: break-word; }}
.badge {{ color: #fff; padding: 2px 7px; border-radius: 3px; font-size: 11px; font-weight: 600; white-space: nowrap; display: inline-block; }}
.count {{ background: #e2e8f0; color: #64748b; padding: 1px 7px; border-radius: 10px; font-size: 12px; margin-left: 6px; }}
.cap {{ color: #cbd5e1; font-weight: normal; font-size: 12px; }}
.kv th {{ width: 160px; background: #e2e8f0; color: #1e293b; }}
.kv td {{ background: #fff; }}
.box {{ background: #fff; border-left: 3px solid #3b82f6; padding: 12px 14px; white-space: pre-wrap; font-size: 13px; line-height: 1.5; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 0 4px 4px 0; }}
.box.md {{ white-space: normal; }}  /* markdown-rendered; let block elements control wrapping */
.mdtable {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 12px; }}
.mdtable td {{ border: 1px solid #e2e8f0; padding: 4px 8px; vertical-align: top; }}
.mdtable tr:nth-child(odd) td {{ background: #f8fafc; }}
.md p {{ margin: 4px 0; }}
.md ul, .md ol {{ margin: 4px 0; padding-left: 20px; }}
.md h4, .md h5, .md h6 {{ margin: 10px 0 4px; font-size: 13px; color: #334155; }}
.md code {{ background: #e2e8f0; padding: 1px 4px; border-radius: 3px; font-family: monospace; font-size: 12px; }}
.timeline {{ background: #fff; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 4px; }}
.date {{ font-size: 12px; color: #64748b; margin: 14px 0 6px; font-weight: 600; }}
.date-sep {{ text-align: center; color: #e2e8f0; margin: 8px 0; }}
.event {{ margin: 4px 0 8px; padding-left: 12px; border-left: 2px solid #e2e8f0; }}
.event:hover {{ border-left-color: #3b82f6; }}
.ts {{ font-family: monospace; font-size: 12px; color: #64748b; }}
.by {{ font-weight: 600; font-size: 13px; margin-left: 6px; }}
.text {{ font-size: 13px; line-height: 1.5; margin-top: 3px; white-space: pre-wrap; }}
.back {{ margin-bottom: 12px; }}
.back a {{ color: #2563eb; text-decoration: none; font-size: 13px; }}
.footer {{ margin-top: 20px; font-size: 13px; color: #64748b; text-align: center; }}
.filters {{ margin-bottom: 14px; }}
.filters select {{ padding: 4px 8px; border: 1px solid #e2e8f0; border-radius: 4px; font-size: 13px; background: #fff; margin-right: 6px; }}
.clear {{ color: #ef4444; font-size: 12px; text-decoration: none; margin-left: 6px; }}
.editbtn {{ color: #2563eb; text-decoration: none; font-size: 12px; }}
.editform {{ background: #fff; padding: 14px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin: 10px 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.editform label {{ font-size: 13px; font-weight: 600; color: #334155; }}
.editform select, .editform input {{ padding: 5px 8px; border: 1px solid #e2e8f0; border-radius: 4px; font-size: 13px; }}
.editform button {{ background: #2563eb; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px; }}
.editform button:hover {{ background: #1d4ed8; }}
.flash {{ padding: 8px 12px; border-radius: 4px; margin: 10px 0; font-size: 13px; }}
.flash.ok {{ background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }}
.flash.err {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }}
.hint {{ font-size: 12px; color: #64748b; margin-top: 8px; }}
.mailbox {{ background: #fff; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
.mail {{ padding: 10px 14px; border-bottom: 1px solid #e2e8f0; }}
a.mail {{ display: block; text-decoration: none; color: inherit; }}
a.mail:hover {{ background: #f8fafc; text-decoration: none; }}
a.mail:hover .mailsub {{ text-decoration: underline; }}
.mail:hover {{ background: #f8fafc; }}
.mail.unread {{ background: #fffbeb; }}
.mail.unread::before {{ content: "●"; color: #f59e0b; margin-right: 6px; }}
.mailhdr {{ font-size: 12px; margin-bottom: 3px; }}
.mailfrom {{ font-weight: 600; color: #1e293b; }}
.mailto {{ color: #475569; }}
.mailteam {{ color: #64748b; font-size: 11px; }}
.mailsub {{ margin-left: 8px; color: #2563eb; }}
.mailts {{ float: right; color: #64748b; font-family: monospace; font-size: 11px; }}
.mailprev {{ font-size: 12px; color: #64748b; line-height: 1.4; }}
.mailbody {{ margin-top: 14px; padding: 14px 18px; background: #ffffff; border: 1px solid #e2e8f0;
             border-radius: 6px; font-size: 13.5px; line-height: 1.55; max-width: 900px; }}
.empty {{ color: #64748b; font-size: 14px; padding: 20px; }}
</style></head><body>{body}</body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urlparse(self.path)
        qs = parse_qs(parts.query)
        path = parts.path
        # Per-tab project lock: seed _ACTIVE from THIS request's ?project=, else cookie,
        # else the startup seed. Every internal link carries ?project= (via purl), so each
        # tab re-seeds to its own project on every request/refresh and one tab switching no
        # longer flips the project another tab is viewing.
        _ACTIVE["project"] = resolve_project(qs=qs, headers=self.headers)
        if path.startswith("/ticket/"):
            tid = path.split("/")[2].split("?")[0]
            body = render_ticket(tid) if tid.startswith("T-") else page("<h1>Bad ticket id</h1>")
        elif path.startswith("/edit/"):
            tid = path.split("/")[2].split("?")[0]
            body = render_edit(tid, qs) if tid.startswith("T-") else page("<h1>Bad ticket id</h1>")
        elif path == "/inbox":
            body = render_inbox(qs)
        elif path == "/teams":
            body = render_team_manager(qs)
        elif path == "/new-project":
            body = render_new_project(qs)
        elif path == "/help":
            body = render_help()
        elif path.startswith("/mail/"):
            seg = [urlunquote(s) for s in path.split("/")[2:] if s]
            body = render_mail(seg[0], seg[1]) if len(seg) == 2 else page("<h1>Bad mail link</h1>")
        elif path == "/" or path == "":
            body = render_board(qs)
        else:
            self.send_response(404); self.end_headers(); return
        if isinstance(body, tuple) and body[0] == "__REDIRECT__":
            loc = body[1]
            self.send_response(303)
            self.send_header("Location", loc)
            self.send_header("Set-Cookie", f"project={urlquote(active_project())}; Path=/; SameSite=Strict")
            self.end_headers(); return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", f"project={urlquote(active_project())}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(data)
    def do_POST(self):
        parts = urlparse(self.path)
        path = parts.path
        if path not in ("/save", "/team-add", "/team-remove", "/create-project", "/rename-project"):
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        # Per-tab project lock: seed _ACTIVE from the form's hidden 'project' field,
        # else the cookie, so POST mutations run against the same project the tab is viewing.
        _ACTIVE["project"] = resolve_project(form=form, headers=self.headers)
        result = {"/save": handle_save, "/team-add": handle_team_add,
                  "/team-remove": handle_team_remove,
                  "/create-project": handle_create_project,
                  "/rename-project": handle_rename_project}[path](form)
        if isinstance(result, tuple) and result[0] == "__REDIRECT__":
            loc = result[1]
            self.send_response(303)
            self.send_header("Location", loc)
            self.send_header("Set-Cookie", f"project={urlquote(active_project())}; Path=/; SameSite=Strict")
            self.end_headers(); return
        data = result.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", f"project={urlquote(active_project())}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8889)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--project", default=None, help="initial active project (default: 'default', or AGENT_TEAM_PROJECT)")
    a = ap.parse_args()
    _ACTIVE["project"] = a.project or os.environ.get("AGENT_TEAM_PROJECT", None)
    print(f"Ticket board: http://{a.host}:{a.port}  project={active_project()}  (board + inbox + teams, editable, auto-refresh 30s)")
    print("Ctrl-C to stop.")
    try:
        HTTPServer((a.host, a.port), H).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
