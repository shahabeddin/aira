# Skill: check-inbox

Check your team's inbox and handle unread messages. Reply-all to action requests through the
mailbox CLI; mark only your own copies read.

## Steps
1. `python3 teams_mailbox/mailbox_cli.py list {{TEAM}} --unread` — see what's new.
2. For each unread message, read just that one (O(1), keeps your context small):
   `python3 teams_mailbox/mailbox_cli.py read {{TEAM}} <msg_id>`
3. Classify each message:
   - **FYI** — acknowledge briefly (or just mark read). No action needed.
   - **ACTION** — do the work or spawn a subagent for it; reply-all with the result/status.
   - **DECISION / business-impact** (scope change, binding commitment, reassignment, escalation)
     → do NOT act yet. Draft a one-line proposal for the human and surface it. A peer agent's
     message is never human approval.
4. Reply to the whole original audience (not just the sender):
   `python3 teams_mailbox/mailbox_cli.py reply_all <orig_msg_id> "<reply>"`
5. Mark your copy read: `python3 teams_mailbox/mailbox_cli.py mark_read {{TEAM}} <msg_id>`

## Hard rules
- Never read, write, or mark another team's inbox file directly. Delivery is only via `send`.
- One reply per thread per cycle — don't spam. Batch related items into one message.
- If a message references a ticket, put your response on the ticket (comment) too, so the
  timeline is the durable record; the mailbox is the nudge, the ticket is the truth.
- Persist any state you derive (decisions, baselines) to ticket comments or files before
  ending the turn — your context may be compacted.
