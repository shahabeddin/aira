---
description: Send a message to one, many, or all teams (each recipient sees the full to-list)
argument-hint: <recipient(s)|all> <message>
---

Send a message via the mailbox CLI. Recipients see who else got it (every copy carries the full `to` list).

**CLI:** `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py"` (fall back to `./teams_mailbox/mailbox_cli.py` if `AGENT_TEAM_TOOLS` is unset and cwd is the repo).

**Determine sender:** `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" whoami` (prints `<team>`; env > `.current_team` > global > unknown); if `unknown`/empty, ask and suggest `/set-team <team>`. Always pass `--by <sender>`.

**Run:**
```
python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" --by <sender> send <recipients> <message...> [--subject "..."]
```
- `<recipients>`: one team, a comma-separated list (`data,quality`), or `all` (all known teams except sender).
- `<message...>`: the body (everything after recipients).
- `--subject "..."`: optional short subject.

**Gating:** routine same-level correspondence is **not** user-gated — just send. Surface a user-approved draft for business-impact mail (scope/decision change, a commitment binding the project, reassignment, escalation). Never send on behalf of a third team not party to the thread.

The CLI appends one copy per recipient to `<recipient>/inbox.jsonl`; each copy has `from=<sender>`, `to=[full recipient list]`, so every recipient sees everyone else who got it.
