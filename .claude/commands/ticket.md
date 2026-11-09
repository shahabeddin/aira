---
description: Work a ticket from the board (pickup, do via subagent, close with checksum)
argument-hint: [ticket-id]
---

Work one ticket: read it, do the work via a subagent, record the result, close it.

**0. No ticket ID given?** Pick one and continue with it as `<id>`:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" board
```
Claim the topmost ready ticket for your team (assigned to you, or unassigned, status `open`; skip `in_progress`/`blocked` ones owned by others). Nothing suitable → say so and stop.

**CLI:** `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py"` (fall back to `./tickets/ticket_cli.py` if `AGENT_TEAM_TOOLS` is unset and cwd is the repo). `--by <team>` defaults to the resolved team — `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" whoami` (env `CLAUDE_TEAM` > `.current_team` > global > unknown; set with `/set-team <team>`). Project is env `AGENT_TEAM_PROJECT` (or `--project`).

**1. Read the ticket:**
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" show <id>
```
Confirm the acceptance criteria are **testable** (verifiable conditions, not narrative). If not, comment asking the owner to tighten them; stop.

**2. Start:** `status <id> in_progress`. If blocked on another team: `status <id> blocked --blocked-reason "waiting on T-XXXX from <team>"`.

**3. Do the work via a subagent** (one ticket per subagent — the subagent's context is discarded on return; this is your per-ticket compaction). When it returns, record the result yourself on the ticket.

**4. Finish:** when the builder work is done and AC met:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" --by <team> close <id>
```
Comment with the artifact path(s) AND a checksum (md5/sha). "Done" without an artifact checksum is an integrity flag. Do **not** `verify` unless you are the verifier team.

**5. Hygiene:** WIP cap ~5 in_progress per team. `blocked` and `reopen` require a reason. Log usage if useful: `usage <id> --model ... --tokens ... --note "..."`.

**If you are the verifier team (role: verifier):** reproduce the AC against the artifact independently — don't trust the builder's claim. Pass: `verify <id>`. Fail: `reopen <id> <reason naming the unmet AC>`. You are read-only by charter: verify or reopen, never build.
