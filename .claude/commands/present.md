---
description: Present project progress or one ticket as slide-style briefings for management and peers
argument-hint: [ticket-id]
---

Present to an audience. You are a developer at a meeting: proposal, approach, results — in simple terms, outcome first. Read-only: never mutate the board to make a slide.

**CLI:** `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py"` (fall back to `./tickets/ticket_cli.py` if `AGENT_TEAM_TOOLS` is unset and cwd is the repo). Project is env `AGENT_TEAM_PROJECT` (or `--project`).

**0. Pick the mode:** ticket ID given → single-ticket mode. No argument → progress mode (whole board). Optional filters `team:<T>` / `epic:<E>` apply to progress mode.

**1. Gather** (read-only):
- Progress mode:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" board
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" stale 7
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" teams list
```
Plus `show <id>` for each ticket done/verified recently (~last 5–8) — their close comments carry the results narrative.
- Ticket mode:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" show <id>
```
Plus `board` for one line of context on where the ticket sits.

**2. Compose slides** — `## Slide N — Title`, ~6–8 slides, one screenful each:
- Progress mode: **Title** (project, today's date, one-line headline "where we are") → **Where we are** (status counts; per-team / per-epic roll-up) → **What we shipped** (recent done/verified tickets — one plain-language outcome sentence each: *what changed, why it matters*) → **In flight** (in_progress, one line each) → **Risks & blockers** (blocked tickets + their blocked-reasons, stale ones, dependency chains) → **Asks & next steps** (decisions/approvals needed from the audience).
- Ticket mode: **Title** (ID + title + status) → **The problem** (why it matters, plain terms) → **Our approach** (reconstructed from comments/history — the key decisions and pivots, not a changelog) → **Results** (each acceptance criterion met or not, in plain words) → **Effort & timeline** (usage records, created→closed elapsed) → **Risks / open questions**.

**3. Render rules:**
- Lead with the outcome, not the process. Every shipped item = one sentence a non-engineer can repeat.
- No jargon walls, no code blocks in body slides. Ticket IDs, artifact paths, and checksums go on one final **technical appendix slide** (for the peers in the room).
- Every claim comes from board data — never invent status, dates, or results. Missing data → say so on the slide ("no usage logged").
- Close with the ask: what you want from management (decision, approval, unblock) or what's next.
