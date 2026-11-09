# Build Prompt — build the agent team system from scratch

> **How to use:** paste this entire file into a fresh Claude Code session as one prompt, or point
> Claude Code at this file (`Read BUILD_PROMPT.md and execute it fully`). It builds a complete,
> self-contained coordination system for teams of AI agent sessions — from nothing, in the
> current directory (or one you choose). Generic: no project-specific data, no pre-existing
> tickets, no references to any other codebase.
>
> **This file BUILDS the system from scratch.** If instead you want to **install** an existing
> repo (clone from GitHub or use a local copy) and onboard a project, use `setup.md` — one
> URL or path and Claude Code does the rest.
>
> **This file is the canonical source of truth for the system.** Keep it in sync with the code
> after every change — spec and implementation move together. A fresh paste must always build
> what the repo currently has.

---

You will build a lightweight, zero-dependency coordination system that lets multiple parallel
Claude Code sessions (or any shell-capable AI agents) run a shared project: a **ticket system**
with an enforced-but-optional verification workflow, an **inter-team mailbox** for async
agent-to-agent messaging, a **web UI** with project switching and a team manager, a **`/team-up`**
command that onboards a new project from a plain-language description, and a **`setup.md`**
entry point that installs an existing repo from a URL or local path. Everything is plain Python 3
(stdlib only) + JSON/JSONL files. No database, no external services, no packages to install.

## 1. Design principles (follow these exactly)

1. **Files are the API.** One JSON file per ticket; one JSONL file per team inbox; one JSON
   manifest per team. Humans can read, diff, and git them.
2. **Atomic writes everywhere.** Any write = write to a temp file in the same dir, then
   `os.replace()` onto the target. Never partial-write a ticket, inbox, or manifest.
3. **Fail loudly, never silently default.** Missing required arguments/env → clear error +
   non-zero exit, not a fallback guess.
4. **Every ticket carries testable acceptance criteria.** Refuse `new` without `--ac` on
   governed projects unless `--force` (with a message saying why).
5. **Verification is a separation of powers — and optional.** A team declared `verifier` is the
   only one that may set `verified`. If NO verifier is declared, the gate is OFF (anyone may
   verify) — for projects that don't use a QA model (marketing, solo dev, etc.).
6. **Teams and projects are first-class DATA, not hardcoded constants.** Teams are discovered
   from on-disk manifests; projects are directories. Adding/removing a team or project never
   requires editing source code.
7. **Project-scoped stores.** All data lives under `projects/<project-name>/`. A new project
   name = a fresh, empty board and empty inboxes. Nothing is shared between projects.
8. **The CLI is the agent interface.** Subcommands, flags, and exit codes are the contract —
   optimize for an agent calling them from a shell and parsing output.
9. **Skills work from any directory.** Skill command files resolve the CLIs via the
   `AGENT_TEAM_TOOLS` env var (path to this repo), falling back to `./` when cwd is the repo.
10. **Make collisions impossible by naming.** Artifact dirs/files include the producer's identity
    (model, config, date, ticket) so two different runs structurally cannot land on the same path.
    An overwrite-guard that only *warns* will eventually be ignored; one that *fails fast at
    startup* changes behavior.

## 2. Directory layout

```
agent_team_tools/            (or current dir)
  tickets/
    ticket_cli.py
    board_server.py           (web UI)
    README.md
  teams_mailbox/
    mailbox_cli.py
    README.md
  templates/
    CLAUDE_TEAM.md            (per-team bootstrap, with {{TEAM}}/{{PROJECT}}/{{ROLE}} placeholders)
    SKILL_check_inbox.md      (reference versions of the working commands below)
    SKILL_ticket.md
    SKILL_lead.md
    README_GOVERNANCE.md
  .claude/commands/           (the active slash commands — same content as the SKILL_* templates,
    team-up.md                 plus frontmatter; installed globally or per-project by setup.md)
    check-inbox.md
    ticket.md
    lead.md
    team-send.md
    set-team.md
    present.md              (no SKILL_* twin — human-session briefing command, not a team-charter skill)
  projects/
    <name>/
      project.json            (project manifest: {"name","workdir"} — workdir is where the team
                              actually works, separate from this coordination store)
      teams/
        <team>.json           (manifest: {"name","role":"verifier"|"coordinator"|"worker",...})
      tickets/
        INDEX.md              (auto-regenerated index of all tickets)
        archive/YYYY-MM/      (archived verified/cancelled tickets)
        T-0001.json ...       (one JSON per ticket)
      teams_mailbox/
        <team>/inbox.jsonl    (one inbox file per team)
  setup.md                    (install entry point — URL or local path → install + onboard)
  uninstall.sh                (inverse of setup.md: removes the Claude Code integration only)
  external-skills.txt         (manifest of external slash-command skills to fetch at install time)
  docs/
    lanes-and-modules.md      (how to carve a project into lanes + deep modules — guidance)
    ml-problem-checklist.md   (lens for /grill-me + coordinator on ML problems)
    running-teams.md          (operating craft: watchers, long-running jobs, ticket hygiene)
  BUILD_PROMPT.md             (this file)
```

- **Teams are just names with an optional role.** A team exists once it has a manifest in
  `projects/<name>/teams/<team>.json`. Roles: `verifier` (the independent checker — only one
  that may `verify`), `coordinator` (the leader — runs `/lead`), `worker` (default). Any names
  work; a project need not declare any verifier (gate OFF) or any coordinator.
- **Backward-compatible discovery:** if a project has no `teams/` manifests, teams are
  discovered by scanning ticket `team` fields + mailbox inbox dirs, with conventional roles
  applied (`quality`→verifier, `supervisor`→coordinator (`scouting`→coordinator kept as a legacy
  alias), others→worker).
- **Project isolation guarantee:** creating or deleting a project never touches another
  project's data. Tickets are separated *by directory*; a project dir is created empty on first use.
- Ticket ids: `T-` + zero-padded 4-digit sequence per project, derived from the max existing id
  (including archive), never reused.
- Message ids: `<from-team>-<unix-epoch>-<counter>` — unique even if two sends land in the same second.

## 3. Ticket system — `tickets/ticket_cli.py`

**Project selection (first-class):** `--project <name>` flag, else env `AGENT_TEAM_PROJECT`, else
a default store path (overridable via `AGENT_TEAM_TICKETS`). Missing project dirs are created on
first use → empty board. All paths resolve under `projects/<project>/tickets/`.

**Team identity (session bootstrap):** each team session is launched with its identity in env:
```
export CLAUDE_TEAM=modeling AGENT_TEAM_PROJECT=<project> AGENT_TEAM_TOOLS=<repo> && claude
```
`CLAUDE_TEAM` is the default for every `--by` flag (explicit `--by` still overrides).
`AGENT_TEAM_PROJECT` scopes every ticket/mailbox call. `AGENT_TEAM_TOOLS` lets the skill commands
find the CLIs from any working directory. For parallel sessions, the launch-time env var is the
right mechanism (it's the only session-scoped state). A solo user who didn't set `CLAUDE_TEAM` at
launch can run **`/set-team <team>`** mid-session, which writes a `<cwd>/.current_team` fallback
file that `actor()` honors; **`whoami`** prints the resolved team + its source. Precedence:
`--by` > `CLAUDE_TEAM` env > `<cwd>/.current_team` > global `~/.config/aira/current_team` > `unknown`.

**Team registry (replaces any hardcoded team set):** a `load_teams()` helper discovers teams
from `projects/<name>/teams/*.json` manifests; with no manifests, it falls back to scanning
tickets + inboxes (conventional roles). `team_names()`, `verifier_team()`, `save_team()`,
`remove_team()` are built on it. All validation (assign, notify, mailbox recipients) goes
through `team_names()`, never a hardcoded list.

**Ticket JSON schema:**
```json
{
  "id": "T-0007", "title": "...", "team": "modeling", "assignee": "modeling",
  "status": "open", "priority": "med", "epic": "", "depends_on": ["T-0005"],
  "labels": [], "blocked_reason": "", "acceptance_criteria": "...", "description": "...",
  "created": {"ts": 0, "by": "supervisor"}, "updated": {"ts": 0, "by": "supervisor"},
  "comments": [ {"ts": 0, "by": "...", "text": "..."} ],
  "history": [ {"ts": 0, "by": "...", "from": "open", "to": "in_progress", "kind": "status"} ],
  "usage": [ {"ts": 0, "by": "...", "model": "...", "effort": "...", "tokens": 0, "platform": "...", "note": "..."} ]
}
```
(`history` is additive — older tickets have no array and get one on the next transition.)

**Subcommands** (all take `--by <team>` to record the actor):
- `projects` lists existing projects (with their recorded workdir, `name -> /path`, if set);
  `projects create <name> [--workdir <path>]` makes a new empty project store (tickets + mailbox
  + teams dirs); with `--workdir` it also `mkdir -p`s that working directory if missing and records
  it in `projects/<name>/project.json` (`{"name","workdir"}`) — the workdir is where the team
  actually works (code/data/deliverables), separate from this coordination store. `projects rename
  <old> <new>` renames one (validates the new name, refuses if it already exists, atomic
  `os.replace`). Safe because no data inside a project references the project name — it's just the
  directory — but team sessions must re-export `AGENT_TEAM_PROJECT=<new>`.
- `teams list` shows discovered teams + roles; `teams add <name> --role verifier|coordinator|worker [--description ""]` registers one; `teams remove <name>` deletes its manifest (existing tickets/inboxes keep their team field).
- `new <team> <title...>` `--status backlog|open` `--priority` `--epic` `--depends-on id,id` `--label a,b` `--desc` `--ac` `--force` — creates + assigns; **requires `--ac` on governed projects** (those with a team registry) unless `--force`; refuses an unknown team unless `--force`. Notifies the owning team's inbox unless `--no-notify`.
- `list [team] [status]` `--label` `--epic` — flat one-line-per-ticket.
- `board [--team T] [--epic E] [--recent N] [--full]` — curated box-drawing view: ACTIVE → RECENTLY COMPLETED → BACKLOG & CANCELLED.
- `show <id>` `--json` — full detail (pretty box-drawing, or raw JSON).
- `status <id> <new-status>` `[--blocked-reason "..."]` — records a comment AND a `history` entry.
- `assign <id> <team>` `--no-notify` — reassign + comment + history + mailbox notification.
- `set <id>` `--title` `--desc` `--priority` `--epic` `--depends-on` `--label` `--blocked-reason` `--ac` (`-` clears).
- `comment <id> <text...>` — append comment.
- `close <id>` — status → done (builder finished, awaiting verification).
- `verify <id>` — **verifier gate:** only succeeds if the actor is the declared verifier team; if
  no verifier is declared, anyone may verify (gate OFF). Others get a clear refusal pointing to `close`.
- `reopen <id> <reason...>` — verification failed: back to in_progress; reason REQUIRED, recorded as comment + history.
- `duplicate <id> <of-id>` `--archive` — mark cancelled as a duplicate.
- `archive <id>` | `archive --all-done` — move `verified`/`cancelled` JSONs to `archive/YYYY-MM/` (never a bare `done`).
- `stale [days]` (default 7) — open/in_progress/blocked/done untouched for N days.
- `usage <id>` `--model` `--effort` `--tokens` `--platform` `--note` — log a self-reported LLM usage record (auto-detects from harness env when not passed; no cost calc).
- `whoami` — print the resolved team + source (env > `.current_team` > global > unknown). Used by the skills to determine the acting team.

**Workflow law:** `backlog → open → in_progress → (blocked) → done → verified`. `verified` is
terminal-success (only via `verify`, gated by the verifier role). Fail path: `reopen` from
`done`/`verified` back to `in_progress` with a required reason. `cancelled` terminal from any
active state. **Adding the first verifier turns the gate on; removing the last verifier turns it off.**

**Hygiene:** regenerate `INDEX.md` after every change. Writes are atomic (§1.2).

## 4. Mailbox system — `teams_mailbox/mailbox_cli.py`

**Same project scoping** (`--project` / env; data under `projects/<project>/teams_mailbox/<team>/inbox.jsonl`).
One JSONL file per team = that team's inbox. **Rule: a process only ever modifies its OWN team's
inbox file; cross-team delivery happens only through `send`, which appends to the recipient's inbox.**

**Team discovery** mirrors the ticket CLI: `load_teams()` reads `projects/<name>/teams/*.json`
manifests, falling back to scanning inbox dirs (conventional roles) when no registry exists.
Recipient validation (`send`, `reply_all`, `all`) uses `team_names()`, not a hardcoded list.

**Message schema (one JSON object per line):** `{id, from, to:[...all recipients...], subject, body, ts, read, reply_to?}`.
Every copy carries the FULL `to` list, so each recipient sees who else got it.

**Subcommands:**
- `--by <team> send <recipients,comma-sep|all> <body...> --subject "..."` — appends one copy per recipient; `all` = all known teams except sender.
- `--by <team> reply_all <orig_msg_id> <body...>` — replies to sender + all original recipients; `orig_msg_id` must be in the replier's OWN inbox; sets `reply_to`.
- `list <team> [--unread]` — one line per message.
- `read <team> <msg_id>` — print ONE message body (O(1): stream the JSONL, don't load the file).
- `mark_read <team> <msg_id>` — flips `read: true` on that team's copy ONLY.
- Atomic appends/rewrites via temp+rename; per-team `flock` on a sidecar `.lock` file serializes
  mark_read rewrites against concurrent appends. Malformed lines are skipped, never crash.

## 5. Team-session wiring — `templates/` + `.claude/commands/`

Two layers: **`templates/`** are the human-readable reference snippets (paste into a session's
CLAUDE.md); **`.claude/commands/`** are the active slash commands (same content + frontmatter)
that `setup.md` installs globally or per-project.

1. **`templates/CLAUDE_TEAM.md`** — per-team bootstrap: identity (`{{TEAM}}`/`{{PROJECT}}`/`{{ROLE}}`),
   env exports (`CLAUDE_TEAM`, `AGENT_TEAM_PROJECT`, `AGENT_TEAM_TOOLS`), ticket + mailbox
   command cheat-sheets, the rules, and the **one-ticket-per-subagent** context discipline
   (spawn a subagent per ticket; record results on the ticket; the subagent's context is
   discarded = per-ticket compaction). Includes "persist state to disk before ending any turn".
   Carries a **`{{LANE}}`/`{{MODULE}}`/`{{INTERFACE}}`** block (own one lane = one deep module;
   stay in your lane; reject shallow pass-through work; deletable when the project uses no lanes)
   and a **context-cadence** block (compact your own context every 1–2 tickets, persisting state
   to tickets + inbox first, re-reading the board as authoritative on wake).
2. **`templates/SKILL_check_inbox.md`** — check own inbox, read each unread via `read`, reply-all
   to action requests via the CLI, mark ONLY own copies read. Hard rule: never touch another
   team's inbox file directly. Business-impact mail → human-gated draft. (Active command:
   `.claude/commands/check-inbox.md`.)
3. **`templates/SKILL_ticket.md`** — ticket cheat-sheet + hygiene (dups before `new`; WIP cap
   ~5/team; blocked needs a reason; every ticket needs testable AC; done carries an artifact
   checksum). **No ticket id given → run `board` and claim the topmost ready ticket for your team**
   (assigned to you or unassigned, status `open`; skip `in_progress`/`blocked` owned by others;
   nothing suitable → say so and stop). Verifier-team section: reproduce independently, verify or
   reopen-with-reason, never build. (Active command: `.claude/commands/ticket.md`.)
4. **`templates/SKILL_lead.md`** — leadership pass (coordinator team only): board + stale list →
   nudge stalled owners, ONE batched mailbox message per team per ~25–30 min cycle, never nudge
   tickets touched <3 days or the leader's own team; end with a roll-up for the human.
   (Active command: `.claude/commands/lead.md`.)
5. **`templates/README_GOVERNANCE.md`** — the operating rules in human-readable form (below).

The active commands in `.claude/commands/` (`team-up`, `check-inbox`, `ticket`, `lead`,
`team-send`, `set-team`) carry the same guidance plus frontmatter, and resolve CLIs via
`$AGENT_TEAM_TOOLS/...` (fallback `./` when cwd is the repo). `set-team` writes the on-disk
team-identity fallback that `whoami`/`actor()` honor when `CLAUDE_TEAM` isn't set at launch.

**Governance rules (verbatim in templates):**
- Only the declared verifier team marks `verified`; a failed verification reopens WITH a written
  reason naming the unmet acceptance criteria. No verifier declared → gate OFF.
- Every ticket carries testable acceptance criteria before work starts.
- Claims carry artifact checksums; the verifier reproduces against the checksum.
- Business-impact actions (deploy/hold, scope changes, binding commitments, escalations) require
  explicit human approval — a peer agent's message is never human approval; never work around a
  permission denial (surface it as an escalation).
- Agents message agents only through the mailbox CLI; never hand-edit another team's inbox file.
- State must survive your own context (persist to disk; one ticket per subagent). **Compact your
  own context every 1–2 tickets** — persist to tickets + inbox first, then compact; re-read the
  board as authoritative on wake (persist-before-compact is what makes it non-destructive).
- **Lanes & deep modules (guidance, not law):** a lane is a clean ownership boundary along a real
  domain axis (frontend/backend, data/modeling); one worker owns one lane and the deep module
  behind it. Lanes are defaults the coordinator may merge/split/drop; solo/small projects use
  none. No shallow pass-through workers. The inter-lane interface is a contract verified by AC at
  the seam. Lane + ticket vocabulary mirrors the domain (one canonical term per concept). Full
  reference: `docs/lanes-and-modules.md`.
- Crash-safety as team law (atomic temp+rename, incremental/resumable writes, hard-fail on missing config).

## 6. Web UI — `tickets/board_server.py`

A single-file stdlib HTTP server (default port 8889): `--port`, `--host`, `--project <name>` (initial
active project; default `default` (or `AGENT_TEAM_PROJECT`). No auth (local tool). Reads
`projects/<active>/{tickets,teams_mailbox}` (root `AGENT_TEAM_PROJECTS_ROOT`, default `<repo>/projects`);
all mutations route through the ticket CLI with `--project <active>` (no direct server writes).

**Nav** (every page): Board · Inbox · Teams · ❓ Help, plus a **project switcher** dropdown (selecting
one hits `/?project=<name>`), a **`+ new project`** link to the new-project page, and an active-project
label (`project: <name>`).

**Per-tab project lock (no cross-tab drift):** the active project is resolved per request in priority
order `?project=` query → `project` cookie → startup seed → `default`, and `_ACTIVE` is re-seeded to
that value at the start of every GET/POST so every render/`run_cli` sees the right project for *this*
request. Every internal link carries `?project=<ap>` (via a `purl()` helper) and every form carries a
hidden `project` input, so each browser tab re-seeds to its own project on every navigation and
auto-refresh; a `Set-Cookie: project=<ap>` is sent on every response as a fallback for bare-URL
requests (back button, manual refresh). One tab switching projects no longer flips the board another
tab is viewing — the original "Ticket T-XXXX does not exist" drift was server-global `_ACTIVE` shared
across all clients; the cookie + URL stamp make it per-tab sticky.

**Board (`/`):** tickets grouped into ACTIVE (in_progress/blocked/open, priority then stale-first) →
RECENTLY COMPLETED (done/verified, most-recent first, **paginated** with first/prev/next/last and a
per-page selector: 8/20/50/All) → BACKLOG & CANCELLED. A **filter bar** filters by status / team /
epic / priority (All = unfiltered). Columns (ID, Team, Status, Pri, Age, Epic, Title) are
**sortable** asc/desc via header links. Status and priority shown as colored badges. Each row links
to the ticket detail and
an edit button. A footer summarizes active/done/backlog/cancelled counts.

**Ticket detail (`/ticket/<id>`):** metadata table (status/team/assignee/priority/epic/labels/
depends-on/blocked/created/updated), description and acceptance criteria rendered as **markdown**
(tables, headings, lists, inline code, bold, italics — HTML-escaped first so content can't inject
markup), a self-reported usage table, and a **chronological timeline** of comments with date
separators. Edit link to the edit page.

**Edit page (`/edit/<id>`):** separate small forms for status, priority, and title; each POSTs to
`/save`, which shells out to the ticket CLI (atomic, recorded as comments + history) and redirects
back with a flash message. Description/AC/labels/epic edits direct to the CLI (hint shown).

**Inbox (`/inbox`):** per-team filter; messages sorted newest-first with unread highlighting (●) and a
160-char preview; each links to a **single-message view** (`/mail/<team>/<id>`) showing full headers
(incl. `in-reply-to` and a read/unread badge) and a markdown-rendered body. Read-only — the web UI
never flips the read flag (teams' unread counts drive their workflows); marking read is via the CLI.

**Team manager (`/teams`):** roster with role badges (verifier/coordinator/worker);
shows whether the verify gate is ON or OFF; add form (name + role + description) and per-team
remove, shelling out to `ticket_cli.py teams add/remove`; a **rename-project form** (new name)
shells out to `ticket_cli.py projects rename <old> <new>` and switches the active project to the
new name. A flash message confirms each action or reports the error.

**New project (`/new-project`):** a form (name) that POSTs to `/create-project` →
`ticket_cli.py projects create`, switches the active project to it, and redirects to the (empty)
board; renders a hint about pointing sessions at it (`export AGENT_TEAM_PROJECT=… CLAUDE_TEAM=…`).

**Help (`/help`):** a minimal human-facing reference — just the slash commands (one line each),
the active project, and the verify-gate status. Full CLI reference and rules live in
`BUILD_PROMPT.md` / `templates/README_GOVERNANCE.md` (linked).

**Colors (modern slate/Tailwind-style palette):** page background `#f1f5f9`, text `#1e293b`, table
headers `#334155` (white text), links `#2563eb`. Status badges: `blocked` `#ef4444`, `in_progress`
`#f59e0b`, `open` `#3b82f6`, `backlog` `#64748b`, `done` `#14b8a6` (teal — awaiting QA), `verified`
`#22c55e` (green — terminal), `cancelled` `#94a3b8`. Priority: `high` `#dc2626`, `med` `#d97706`,
`low` `#64748b`. Roles: verifier `#22c55e`, coordinator `#7c3aed`, worker `#94a3b8`. (`done` and
`verified` are deliberately distinct.)

**Badge + base CSS (write these rules exactly — the palette alone is not enough; without white
badge text the colors read as "off"):** `* { box-sizing: border-box; }`; `body { font-family:
-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background:
#f1f5f9; color: #1e293b; max-width: 1300px; margin: 0 auto; }`; `table { width: 100%;
border-collapse: collapse; background: #fff; }`; `th { background: #334155; color: #fff;
text-align: left; padding: 7px 10px; }`; `td { padding: 6px 10px; border-bottom: 1px solid
#e2e8f0; }`; `tr:hover td { background: #f8fafc; }`; `a { color: #2563eb; text-decoration: none; }`;
**`.badge { color: #fff; padding: 2px 7px; border-radius: 3px; font-size: 11px; font-weight: 600;
white-space: nowrap; display: inline-block; }`** — badges set only `background` inline per the
palette above; the white text comes from this rule. Add a `<meta charset="utf-8">` as the first
`<head>` child on every page (so unicode renders). A `.meta` line (12px, `#64748b`) under each
page title carries the auto-refresh note + counts.

Auto-refresh 30s on read-only pages (board, inbox, detail) via `<meta http-equiv="refresh"
content="30">` in `<head>`; edit/team-manager/help/new-project pages do **not** auto-refresh.
**Re-read tickets and mailbox from disk on every request** (glob the JSON/JSONL files fresh each
GET) — never cache ticket/mailbox data in module scope, or a 30s refresh serves stale state.
Degrade gracefully on an empty project (empty board must render).

## 7. `/team-up` and `setup.md` — onboarding

**`.claude/commands/team-up.md`** — a slash command that onboards a project in one step:
1. List existing projects; pick one or create a new one. **The session running `/team-up` is the
   supervisor** — set its identity with `/set-team supervisor`. For a new project, ask where the
   **working directory** is (where the team works — separate from the coordination store) and
   create it with `ticket_cli.py projects create <name> --workdir <path>` (mkdir -p + record in
   `project.json`); then `cd` into that workdir — all subsequent work happens there. For an
   existing project, read its workdir from `project.json` (or `projects` list) and `cd` there.
2. For a new project, the coordinator (the **supervisor**) leads the requirements phase BEFORE
   proposing a roster. First interview the brief with `/grill-me` (external skill, if installed)
   until it's concrete: deliverables, scope, constraints, success criteria. This is the **default
   first step — do not skip it**, and do not skip it *because* the prompt is short; a short prompt
   is the strongest reason to grill. Only skip if the brief is already a concrete, committed plan.
   If the brief is an **ML problem** (prediction/classification/risk/scoring/detection/learning
   from data), paste `docs/ml-problem-checklist.md` into the grilling session as the lens
   (data/labeling, taxonomy, requirements incl. whether ML adds value at all, model selection,
   features, OOD eval, notebooks) — an ML project typically carves into a **data** lane and a
   **modeling** lane. THEN propose a roster of **lanes + roles** — a lane is a clean ownership
   boundary along a real domain axis (frontend/backend, data/modeling); one worker owns one lane
   and the deep module behind it. Lanes are **defaults, not dogma** — the coordinator may
   merge/split/drop them, and solo/small projects use none (see `docs/lanes-and-modules.md`). Role
   questions are orthogonal: "who independently checks the work?" (→ `verifier`); "who
   coordinates?" (→ `coordinator`, named `supervisor` by default); everyone else a `worker` owning
   a lane. For each lane, write a one-line **module interface** into the team `--description`
   (what the lane exposes to the others). Confirm, then `teams add` each.
3. Start the board on the **first free port from 8889 up** (don't assume 8889 is free — another
   board may hold it). For each candidate port `$p`, curl `http://127.0.0.1:$p/`; if it returns
   200 the port is taken (skip), else launch `board_server.py --project <name> --port $p --host
   127.0.0.1` in the background and curl-confirm 200. Remember `$p` for the join card. Re-running
   `/team-up` reuses a board already up for this project instead of starting a second one.
4. Print the join card: board URL `http://127.0.0.1:$p`, one
   `cd <workdir> && export CLAUDE_TEAM=<team> AGENT_TEAM_PROJECT=<name> AGENT_TEAM_TOOLS=<repo> && claude`
   line per team, verifier-gate status, pointers to `templates/` and `docs/lanes-and-modules.md`.

Archetypes (lanes · roster): ML research (data·modeling — supervisor+data+modeling+quality-verifier),
full-stack product (frontend·backend·data — pm+frontend+backend+data+qa-verifier), product w/ PM
(frontend·backend — pm-coordinator+frontend+backend+qa-verifier), marketing (content·social·design
— content+social+design, no verifier), publishing (writing·editing — writer+editor-verifier),
security review (recon·analysis — recon+analyst+reviewer-verifier), solo dev (no lanes — one worker, no gate).

**`setup.md`** — the install entry point (drop a URL or a local path into a fresh Claude Code
session). It: locates the repo (clone from GitHub or use the local path) → `TOOLS_DIR`; asks
global-vs-local skills and copies the 6 command files; **fetches external skills** listed in
`external-skills.txt` (one `curl` per `<filename> <url>` entry into the chosen commands dir; warn
and continue on fetch failure, don't abort); sets `AGENT_TEAM_TOOLS`; then runs `/team-up`.
Idempotent. Example external skill: `grill-me.md` → `/grill-me`, which interviews a loose idea
into a committed plan (useful for the coordinator before turning a brief into tickets).

**`external-skills.txt`** — a manifest of externally maintained slash-command skills, one per
line (`<filename> <source-url>`, `#` comments). The skill **content is not vendored** in the
repo; `setup.md` fetches each URL at install time and `uninstall.sh` removes the installed
copies. To add another external skill, append a line here.

**`uninstall.sh`** — the inverse of `setup.md`'s Claude Code steps: removes the 6 built-in
slash-command files **plus any external-skill filenames listed in `external-skills.txt`** from
`~/.claude/commands/` (and `<cwd>/.claude/commands/` if installed locally, never the repo's own
source copies), and strips the `AGENT_TEAM_TOOLS` export from `~/.zshrc`/`~/.bashrc` (with a
`.bak` backup). Never touches the repo, `projects/`, tickets, inboxes, or board data. `--dry-run`
previews. `setup.md` does not invoke it; it's a standalone script the user runs directly.

## 8. Build order + self-verification (do all, in order)

1. Directory skeleton + both CLIs with `--help` working (including `projects`, `teams` subcommands).
2. Ticket lifecycle smoke test on a scratch project `smoketest`:
   - `ticket_cli.py projects create smoketest`; `teams add builder --role worker`; `teams add qa --role verifier`.
   - `--by pm new builder "First" --ac "file X exists and is non-empty"` → `T-0001`. (Use `--force` for `pm` if not registered.)
   - Refuse `new` without `--ac` (registry exists) → warning + non-zero; `--force` overrides.
   - `status` transitions backlog→open→in_progress→done; `verify` as `--by builder` → **refused**
     (qa is verifier); `verify` as `--by qa` → **verified**; `reopen` without reason → refused;
     with reason → in_progress + comment + history entry.
   - `teams remove qa` → gate OFF; `verify` as `--by builder` now succeeds.
   - `archive` a verified ticket → `archive/YYYY-MM/`; INDEX.md regenerates.
3. Mailbox smoke test: `send` to two recipients → both inboxes have the identical-id line; `read`
   one; `reply_all` from a recipient → sender + other recipient get the reply with `reply_to` set;
   `mark_read` affects only that team's copy. Confirm recipient validation uses discovered teams.
4. **Project isolation test:** create `alpha` with one ticket + one team + one message; create
   `beta` → its `board` shows ZERO tickets and empty inboxes; nothing in `alpha` changed.
5. Templates + governance README (with the **lanes & deep modules** and **compact-every-1–2-tickets**
   sections) + the three authored docs (`docs/lanes-and-modules.md`, `docs/ml-problem-checklist.md`,
   `docs/running-teams.md` — write verbatim from §9) + the 6 `.claude/commands/` files (`team-up`,
   `check-inbox`, `ticket`, `lead`, `team-send`, `set-team`) written; `setup.md`, `uninstall.sh`,
   and `external-skills.txt` (write verbatim from §9 — the URL must be exact; do not invent one) written.
   **Then fetch external skills** so they're usable as project-local slash commands from this dir:
   read `external-skills.txt` and for each `<filename> <url>` line, `curl -fsSL "<url>" -o
   ".claude/commands/<filename>"` (warn and continue on failure — don't abort the build). This
   installs `/grill-me` (and any future external skills) into the build's own `.claude/commands/`,
   so the supervisor's grill-by-default step in §8 can actually run it. (Global install to
   `~/.claude/commands/` is `setup.md`'s job, not the build's.)
6. `board_server.py --project smoketest` renders every page: board (with T-0001, filter bar, sortable
   columns, pagination), `/ticket/T-0001` (metadata + AC + timeline), `/edit/T-0001` (status/priority/
   title forms), `/inbox` (per-team, unread highlight), `/mail/<team>/<id>` (single message),
   `/teams` (roster + role badges + gate status), `/new-project`, `/help` (slash-command list). Nav
   shows the project switcher + active-project label on every page. Empty project renders without error.
7. **UI user actions** (each goes through the CLI with `--project`, atomic + recorded): POST `/save`
   to edit a ticket's status, priority, and title — confirm the change lands on the ticket (comment +
   history entry) and a flash message shows; POST `/team-add` to add a team via `/teams` → it appears
   in `teams list`; POST `/team-remove` to remove it; POST `/create-project` from `/new-project` →
   board switches to the new (empty) project. Switch the active project via the nav dropdown
   (`/?project=<name>`) → board re-renders for that project.
8. Final README.md at the root: what it is, the two CLIs' usage, `projects`/`teams` management,
  the workflow law + optional verify gate, the web UI, `/team-up`, `setup.md` (URL/path install),
  `uninstall.sh`, and "how to point a Claude session at this" (`AGENT_TEAM_TOOLS` +
  `AGENT_TEAM_PROJECT` + `CLAUDE_TEAM`, paste `templates/CLAUDE_TEAM.md`). A **`mermaid` org-chart
  diagram** (human → coordinator/workers/verifier → shared flat-file store, with done→verify→verified
  and reopen edges) renders the architecture. A short **Demo section** describes the web UI in
  prose. Do **not** reference a `docs/board.png` screenshot in the README you write — a from-scratch
  build cannot capture a screenshot, and a broken image link is worse than prose. (The canonical
  GitHub repo carries `docs/board.png` as a real-repo asset added separately; its absence in a
  from-scratch build is **expected, not a deviation** — do not flag it.) Note `BUILD_PROMPT.md` is
  the from-scratch rebuild spec, `docs/lanes-and-modules.md` is the lane/module guidance, and
  `docs/running-teams.md` is the operating craft.

When all self-verification steps pass, **this build session becomes the supervisor** and runs the
onboarding itself — don't just hand the user an empty board. First delete the smoke-test projects
(per the "starts every project empty" rule) so `projects/` is empty. Set this session's identity:
run **`/set-team supervisor`** (writes `.current_team`, so every CLI `--by` resolves to
`supervisor`), and ensure `AGENT_TEAM_TOOLS` points at the repo you just built. Then execute the
**`/team-up` onboarding flow** (§7 / `.claude/commands/team-up.md`): ask the user for the project
name and its **working directory** (where the team will actually work — separate from the
coordination store, which stays under `projects/<name>/`); create it with
`ticket_cli.py projects create <name> --workdir <path>` (this `mkdir -p`s the workdir if missing
and records it in `projects/<name>/project.json`); `cd` into the workdir; grill the brief with
`/grill-me` (loading `docs/ml-problem-checklist.md` as the lens if it's an ML problem); propose a
roster of lanes + roles; register the teams; and start the board in the background on the **first
free port from 8889 up** (curl each candidate `http://127.0.0.1:$p/`; 200 = taken, skip; else
launch `python3 tickets/board_server.py --project <name> --port $p --host 127.0.0.1 &` and
curl-confirm 200). Leave it running. Then print the completion summary: file tree, smoke-test
transcript highlights, and the **join card** — board URL `http://127.0.0.1:$p`, the workdir, and
one line per team for the user to launch in new terminals:
`cd <workdir> && export CLAUDE_TEAM=<team> AGENT_TEAM_PROJECT=<name> AGENT_TEAM_TOOLS=<repo> && claude`.
State that this session is the supervisor (already in the workdir) and whether the verify gate is
ON or OFF. Do not kill the board server — leave it running for the user.

## 9. Authored files (write these files verbatim)

Step 5 of the build order creates `docs/lanes-and-modules.md`, `docs/ml-problem-checklist.md`,
`docs/running-teams.md`, and `external-skills.txt`. Write each with the exact content below —
these are authored, not fetched, so a from-scratch paste must reproduce them character-for-character.
For `external-skills.txt` this is especially load-bearing: the URL must be the exact one below
(it resolves with curl); do **not** invent or guess a URL, or `/grill-me` will fail to install.
(The `/grill-me` skill **content** is not authored here — `external-skills.txt` only records the
URL; `setup.md` fetches the content at install time.)

### `docs/lanes-and-modules.md`
```markdown
# Lanes & deep modules — how to carve an agent-team project

> Guidance, not law. The coordinator decides whether a project uses lanes at all.
> Sources: [*A Philosophy of Software Design*](https://www.goodreads.com/book/show/58665335) (Ousterhout),
> [*Domain-Driven Design*](https://www.goodreads.com/book/show/179133-domain-driven-design) (Evans),
> *Working Effectively with Legacy Code* (Feathers), *The Design of Design* (Brooks),
> *The Pragmatic Programmer* (Hunt & Thomas).

A lane is a clean ownership boundary along a **real domain axis** — frontend / backend,
data / modeling, recon / analysis. One worker owns one lane. A bigger project composes
more lanes; a small or solo project uses none. Carving lanes is a default the coordinator
can merge, split, or drop to fit the work.

## 1. Lanes are defaults, not dogma
- **Principle:** structure the team around real domain boundaries, not org convenience.
- **For a session:** if your project has lanes, you own one and stay in it. If the
  coordinator declared no lanes (solo, marketing, small build), just work the board.

## 2. Deep modules, not shallow work
- **Principle:** a module is deep when it offers rich behavior behind a narrow interface
  (Ousterhout). A worker who only forwards to another lane is a shallow module —
  indirection with no value.
- **For a session:** own a cohesive subsystem end-to-end. If a ticket only asks you to
  relay to another lane, comment "this is a mis-carved lane" and stop — don't staff a
  pass-through.

## 3. Align on the concept before implementing
- **Principle:** resolve the design concept and the inter-lane contract before code
  (Brooks). Ambiguous requirements diverge across lanes into semantic friction.
- **For a session:** before cross-lane work, agree the contract at the seam and pin it in
  the ticket's acceptance criteria. AC verifies the contract, not internal plumbing.

## 4. Ubiquitous vocabulary
- **Principle:** code and tickets use the domain's own words; one canonical term per
  concept everywhere (Evans). No `Manager`/`Helper` synonyms for the same thing across lanes.
- **For a session:** name your lane and your artifacts as the domain names them. If two
  lanes call the same thing by different names, surface it and pick one.

## 5. Combat entropy on every ticket
- **Principle:** the cost of change should stay constant; invest in design daily
  (Hunt & Thomas; Beck). A tactical hack at a lane boundary becomes a permanent liability.
- **For a session:** if a feature fights a lane boundary, refactor the boundary first
  (Boy Scout rule), then apply the change. Leave the seam cleaner than you found it.

---

**Where lanes live in this system:** a lane is recorded as a team with a one-line
*module interface* in its `--description` (what the lane exposes to the others; everything
else is internal). The board's `/teams` page shows it. No special CLI field — lanes ride
on the existing description.
```

### `docs/ml-problem-checklist.md`
```markdown
# ML problem checklist

> **Load this when the project is an ML problem.** Use it as the lens for `/grill-me` — paste this
> whole file into the grilling session so the interview covers the decisions that actually determine
> whether ML works here — and use it as the coordinator's guide when turning an ML brief into lanes
> + tickets. It pairs with [`docs/lanes-and-modules.md`](lanes-and-modules.md): an ML project
> typically carves into a **data** lane and a **modeling** lane, each owning a deep module.

## 1. Data & labeling
- **What data is available?** Sources, volume, time range, coverage. Where are the gaps and the
  biases in collection?
- **How is labeling done?** Human labels, weak supervision, proxies? Quantify label noise and
  inter-annotator agreement.
- **Taxonomy.** Define the label space precisely — classes, severities, mutually-exclusive vs.
  multi-label. A fuzzy taxonomy poisons everything downstream; settle it before any modeling.

## 2. Requirements (the "do we even need ML" guard)
- **Latency budget** — per-inference and throughput.
- **Precision / recall / FPR targets**, and the **cost asymmetry** of false positives vs. false
  negatives. Which error hurts more? This sets the operating point, not the model.
- **Will ML really add value here?** Could rules, thresholds, or heuristics match the target at a
  fraction of the cost and risk? State the non-ML baseline that ML must beat. If you can't name it,
  you're not ready to build.

## 3. Model selection
- **Start simple.** Logistic regression / single-feature thresholds as a baseline. Don't reach for
  a neural net before a linear model is tried and beaten.
- **Candidates:** traditional (logistic regression, XGBoost, random forest), small language models
  (SLMs), neural nets — and **combinations**: a **cascade** (fast cheap model → slow accurate model
  on the uncertain slice), **ensemble**, or **stacking**.
- **Which is best *for the constraints*** — latency, data size, interpretability, OOD robustness —
  not just the highest ROC on an in-distribution test set.

## 4. Features
- **Feature extraction & engineering:** what signals exist, what's leaky, and what's available at
  *inference* time (not just training). A feature you can't get in production is not a feature.
- **Representations** (NN/SLM): pretrained embeddings vs. trained-from-scratch, freezing vs.
  fine-tuning, what to tokenize / window / aggregate.

## 5. Evaluation
- **Out-of-distribution evaluation is mandatory.** Time splits, new domains, drift — report OOD
  performance separately from in-distribution. A random holdout hides the failure you'll ship.
- **Metrics tied to requirements:** ROC/PR curves at operating points, FPR at target recall,
  calibration. A single accuracy number is not evaluation.

## 6. Notebooks (reproducible artifacts)
- **Data-analysis notebooks:** comprehensive EDA for insight into the data — distributions,
  missingness, class balance, subpopulation breakdowns, label-noise inspection.
- **Modeling notebooks:** class / probability weights, ROC/PR curves, training trajectories
  (loss + metrics over epochs), confusion matrices, error analysis.

Every notebook is an **artifact**: it lands on a ticket with a path **and a checksum**, so the
verifier can reproduce it. "Done" without a checksum is an integrity flag, not a finish line (see
[`templates/README_GOVERNANCE.md`](../templates/README_GOVERNANCE.md)).
```

### `docs/running-teams.md`
```markdown
# Tips for running agent teams on this system

Operating guidance for teams of Claude Code (or any shell-capable AI) sessions running on
the ticket board + mailbox. The enforceable rules live in
[`templates/README_GOVERNANCE.md`](../templates/README_GOVERNANCE.md); this is the softer
craft of running them well.

## Team sessions
- Check the inbox and board at a steady cadence; reply-all to keep threads whole. Batch — one
  status message per counterpart per cycle, not a stream.
- Leadership nudges: never more than one message per team per ~25–30 min; skip teams actively
  working (touched <3 days); never nudge your own tickets.
- Escalate early with specifics: a blocking message that says "X failed at Y, tried Z" gets
  unblocked faster than "X is stuck."

## Watchers / monitors (subagent design, if you use background watchers)
- **Poll, don't `tail -f`** — tools that rewrite files atomically (temp+rename) break tailers;
  re-resolve the path every pass instead.
- Persist watcher state (seen-ids, baselines) to a disk file with atomic writes; treat it as
  authoritative on every wake. Dedup on composite keys (ids alone may collide).
- Emit one triaged line per event (`[ACTION|FYI] id from sender re: subject — summary`) so the
  expensive main session only wakes for what matters.
- A watcher's "completed" task-notification often fires on turn-end even while its loop is live
  — verify liveness with `ps` before assuming it died.
- For remote hosts behind short-lived certs (e.g. Teleport/tsh): plain `tsh ssh host cmd`
  **self-renews** credentials; the `tsh proxy ssh` undercurrent used inside ssh ProxyCommands
  does **not** — run a periodic plain-`tsh-ssh` keepalive if you hold long-lived watchers
  through it. Launch long remote jobs with `nohup … > log 2>&1 < /dev/null &` so they survive
  disconnects.

## Long-running jobs generally
- Progress bars to **stderr** (a 0-byte log for 20 min is indistinguishable from a hang); write
  results incrementally, not at completion; make loops resumable from the last completed record;
  skip-and-log single bad items instead of dying; set client-side timeouts on paid API calls.

## Ticket hygiene
- Check for duplicates before `new`; keep per-team work-in-progress capped (~5);
  `archive --all-done` after promotion of durable findings to long-term memory/docs; every state
  change leaves history — the ticket timeline is your audit trail.

## Docs discipline (multi-session projects)
- Fix who writes where: builders land findings in tickets + an append-only log; one party owns
  the distilled reports and decides what's worth lifting. Never let report updates race ahead of
  verification — gate "publish the result" on the verifier's verdict.
- Numbers must be identical everywhere they appear; when two measurements of the same quantity
  exist, cite both with their sources rather than silently picking one.
```

### `external-skills.txt`
```text
# External slash-command skills installed by setup.md alongside the built-in commands.
#
# The skill CONTENT is NOT vendored in this repo — setup.md fetches each URL at install
# time and writes it to the chosen commands dir (global ~/.claude/commands/ or local
# .claude/commands/). uninstall.sh removes these too. This keeps external, independently
# maintained skills out of the repo while still installing them as part of setup.
#
# Format:  <filename> <source-url>
#   filename = the slash-command file (e.g. grill-me.md → /grill-me)
#   url      = raw text URL of the skill file (must resolve with curl)
# Lines starting with # are comments. To add another external skill, append a line.

grill-me.md https://raw.githubusercontent.com/mattpocock/skills/main/docs/productivity/grill-me.md
```

## 10. Out of scope (do not build)

- Authentication, multi-user permissions, or networking beyond the local web UI.
- Any specific project's data, tickets, or history — this system starts every project empty.
- Migrations or importers.
