---
description: Coordinator leadership pass — nudge stalled work, roll up to the human
---

Run a leadership pass over the board. You are the **coordinator** team. You coordinate; you do not build.

**CLI:** `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py"` (fall back to `./tickets/ticket_cli.py`). Mailbox: `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py"`. `--by` defaults to the resolved team (`... whoami`; set with `/set-team <team>`); project is `AGENT_TEAM_PROJECT`.

**Cadence:** ~every 25–30 min. **Never more often.** ONE batched mailbox message per team per cycle.

**1. Review:**
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" board
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" stale 7
```

**2. Nudge stalled tickets** owned by other teams: batch all nudges for one team into a single mailbox message.
```
python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" --by <your-team> send <team> "T-XXXX stalled: <one-line>. Can you unblock or update?" --subject "nudge: T-XXXX"
```
Do **not** nudge tickets touched in the last 3 days, or your own team's tickets.

**3. Roll up to the human** (one message / scratchpad): per-team status (active/blocked/stale counts), what you nudged, what needs the human.

**Rules:** peer correspondence is ungated. Business-impact commitments (scope changes, reassignments, holds, escalations) → human gate (one-line draft, don't commit without approval). A permission denial becomes an escalation, never a workaround.
