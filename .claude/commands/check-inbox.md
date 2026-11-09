---
description: Read and handle unread messages; reply-all to the original audience
argument-hint: [team]
---

Check this team's mailbox, handle unread messages, and **reply-all** to each original audience.

**CLIs:** `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py"` (fall back to `./teams_mailbox/mailbox_cli.py` if `AGENT_TEAM_TOOLS` is unset and cwd is the repo). `--by <team>` defaults to env `CLAUDE_TEAM`.

**HARD RULE — never write directly into another team's mailbox file.** Only ever read/list/mark-read/append in **this team's own** inbox. Replying *to* another team via `send`/`reply_all` is normal same-level correspondence and IS allowed (the CLI delivers on your behalf — you never touch their file).

**User approval IS warranted** for mail with **important business impact** (scope/decision change, a commitment binding the project, reassignment, escalation). Otherwise just reply — don't hold routine status updates for approval.

**1. Determine team:** `$1` if given; else resolve via
`python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" whoami` (prints `<team>` + source; env >
`.current_team` > global > unknown). If `unknown`/empty, ask the user once and suggest `/set-team <team>`.

**2. List unread:**
```
python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" list <team> --unread
```

**3. For each unread, in order:**
1. Read the ONE message body (O(1), doesn't load the whole inbox):
   `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" read <team> <msg_id>`
2. Summarize to the user (from / `to=[full list]` / subject / body).
3. If it requests action: reply via `reply_all` (routine, not user-gated). Surface a user-approved draft only for business-impact mail.
   `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" --by <team> reply_all <orig_msg_id> "<reply>"`
4. Mark only this team's own copy read:
   `python3 "$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py" mark_read <team> <msg_id>`

**4. If no unread:** respond `Inbox empty for <team>.` and stop.

**Notes:** Reply-all is the default (group discussions stay on the whole thread). The mailbox is the nudge; the ticket is the durable record — also comment on any referenced ticket.
