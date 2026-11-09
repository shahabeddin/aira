# Skill: lead (coordinator team only)

Run a leadership pass over the board and nudge stalled work. You are the coordinator team
(role: coordinator). You coordinate, you do not build.

## Cadence
Run this roughly every 25–30 minutes. **Never more often.** One batched mailbox message per
team per cycle — anti-spam.

## Pass
1. `python3 tickets/ticket_cli.py board` — review ACTIVE, RECENTLY COMPLETED, BACKLOG.
2. `python3 tickets/ticket_cli.py stale 7` — find open/in_progress/blocked untouched ≥ 7 days,
   and idle `done` (QA backlog).
3. For each stalled ticket owned by another team: nudge that team **once**, by mailbox,
   referencing the ticket id and the specific blocker. Batch all nudges for one team into a
   single message.
   `python3 teams_mailbox/mailbox_cli.py send <team> "T-XXXX stalled: <one-line>. Can you
   unblock or update?" --subject "nudge: T-XXXX"`
4. Do **not** nudge:
   - tickets touched in the last 3 days (they're active), or
   - your own team's tickets (coordinate outward, not inward).

## Escalation roll-up for the human
End each pass with a short roll-up (one message to the human / on your own scratchpad):
- per-team status (active count, blocked count, stale count)
- what you nudged this cycle
- what needs the human (decisions, approvals, unblocks you can't resolve peer-to-peer)

## Rules
- Same-level (peer) correspondence is ungated — you can nudge, ask, inform other teams freely.
- Business-impact commitments (scope changes, reassignments, holds, escalations) → human gate.
  Surface a one-line draft; don't commit on the project's behalf without approval.
- If a team is blocked on a permission denial, surface it as an escalation, never launder the
  permission by asking another session to do the denied thing.
