# Team tickets

Filesystem ticket system for teams of Claude Code sessions. One JSON file per ticket:
`tmp/tickets/T-XXXX.json`. `INDEX.md` regenerates on every change. Verified/cancelled tickets archive
to `tmp/tickets/archive/YYYY-MM/`. Create/reassign drops a notice in the team's mailbox
(`tmp/teams_mailbox/<team>/`) so `/check-inbox` surfaces it.

## Schema
`{id, title, description, team, assignee, status, priority, epic, labels[], depends_on[], blocked_reason, acceptance_criteria, created{ts,by}, updated{ts,by}, comments[]}`
- `team`/`assignee`: supervisor | data | modeling | quality
- `status`: backlog | open | in_progress | blocked | done | verified | cancelled
  - workflow: `backlog → open → in_progress → (blocked) → done → verified`
  - `done` = builder finished, ready for Quality review; `verified` = Quality passed (terminal)
- `priority`: low | med | high
- `epic`: grouping label (e.g. `v6-retrain`, `patronus-eval`, `v6-hardening`, `data-ingest-jailbreak-technique`)
- `labels[]`: cross-cutting tags (`eval`, `data-ingest`, `recon`, `needs-user-OK`, `needs-eval`, `recurring`)
- `depends_on[]`: ticket ids this is blocked by; `blocked_reason`: why a `blocked` ticket is stuck

## CLI
```
python3 tmp/tickets/ticket_cli.py --by <actor> new <team> <title...> [field flags] [--status backlog|open] [--no-notify]
python3 tmp/tickets/ticket_cli.py list [team] [status] [--label L] [--epic E]
python3 tmp/tickets/ticket_cli.py show <id>
python3 tmp/tickets/ticket_cli.py status <id> <status> [--blocked-reason "..."]
python3 tmp/tickets/ticket_cli.py assign <id> <team> [--no-notify]
python3 tmp/tickets/ticket_cli.py set <id> [field flags] [--title ...]
python3 tmp/tickets/ticket_cli.py comment <id> <text...>
python3 tmp/tickets/ticket_cli.py close <id>             # -> done (builder finished; ready for QA)
python3 tmp/tickets/ticket_cli.py verify <id>            # -> verified (Quality passed; terminal) [Quality only]
python3 tmp/tickets/ticket_cli.py reopen <id> <reason...> # QA fail -> in_progress + required reason
python3 tmp/tickets/ticket_cli.py duplicate <id> <of-id> [--archive]
python3 tmp/tickets/ticket_cli.py archive <id> | archive --all-done   # archives verified|cancelled (NOT done)
python3 tmp/tickets/ticket_cli.py stale [days]
```
Field flags (new/set): `--desc --priority --epic --depends-on id1,id2 --label a,b --blocked-reason "..." --ac "..."` (use `-` to clear). `--ac` = testable acceptance criteria Quality verifies against before `verify`. `--by` overrides `CLAUDE_TEAM`. The `/ticket` slash command wraps this CLI.

## Long-term hygiene (anti-rot)

1. **Lifecycle + archival** — `new` defaults to `backlog` (triage moves it to `open`); `close` → `done` when the builder finishes; Quality `verify` → `verified` (terminal) or `reopen <id> <reason>` → `in_progress`. `archive --all-done` periodically moves **verified/cancelled** out of the active index into `archive/YYYY-MM/` (not `done`, which still awaits QA). Active list stays short.
2. **Epics** — group related tickets under one `epic` so duplicates and orphans are obvious; close a whole epic together.
3. **Dependencies** — set `depends_on` so conditional tickets have a clear trigger (e.g. T-0004 depends_on T-0005). Blocked tickets must carry a `blocked_reason`.
4. **Dedup** — before `new`, `list` to check for an existing similar ticket; use `duplicate <id> <of-id>` to close a dup and link it.
5. **Staleness** — `stale 7` lists open/in_progress/blocked/**done** tickets untouched >= 7 days (a `done` ticket sitting idle = QA backlog); triage resolves or closes them.
6. **WIP cap** — per team, ~5 open tickets max; finish/close before starting new.
7. **Tickets ≠ knowledge base** — when a closed ticket holds a durable decision/finding, promote it to memory (`~/.claude/.../memory/`), then archive the ticket.
8. **Title convention** — verb + object + qualifier ("Ingest …", "Eval …", "v6 retrain …") for searchability.
9. **Comment formatting** — `show`/`board` print comment text verbatim (no rendering), but write it *in* markdown anyway — raw files and most viewers render it, and even unrendered it's more scannable than a prose wall:
   - Any closing/results comment on a `done`/`verify` transition includes a `**Docs:**` line listing where the full writeup lives (notebook path, report path, CSV, etc.) — don't make the next reader grep for it.
   - Quantitative results go in a markdown table (`| metric | value |`), not an inline comma-separated list.
   - Use bold labels (`**Result:**`, `**Recommendation:**`, `**Caveat:**`) instead of ALL-CAPS prose runs.

## Weekly triage
Owned by **Scouting** (ticket T-0009). Steps: `list` → `stale 7` → dedup/`duplicate` → confirm each `blocked` ticket still has a path (or re-scope) → enforce WIP cap → promote durable findings to memory → `archive --all-done` → 1-line board summary to the user.

## Upgrade trigger → GitHub Issues
If the active board grows past ~20-30 live tickets or triage becomes a chore, migrate to GitHub Issues
on the project's repo via `gh issue` — first-class labels, milestones, assignees,
projects; doesn't rot the same way. Trigger: active ticket count > 25 for 2 consecutive triages, or any
single epic > 10 tickets.
