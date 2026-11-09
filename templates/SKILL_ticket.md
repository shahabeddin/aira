# Skill: ticket

Work tickets from the board. One ticket per subagent; record results on the ticket.

## Pickup
1. `python3 tickets/ticket_cli.py board` — see ACTIVE (priority, then stale-first) and BACKLOG.
2. Pick one ticket in your team's lane. `show <id>` to read description + acceptance criteria.
3. Before starting work, re-confirm the acceptance criteria are **testable** (verifiable
   conditions, not narrative). If they aren't, comment asking the owner to tighten them.

## Do the work
4. Spawn a **subagent** to do the actual work for this one ticket. Record the result yourself
   on the ticket when the subagent returns — the subagent's context is discarded (this is your
   per-ticket compaction).
5. While working: `status <id> in_progress`. If you're stuck on another team, `status <id>
   blocked --blocked-reason "waiting on T-XXXX from modeling"`.
6. Log self-reported usage if useful: `usage <id> --model ... --tokens ... --note "..."`.

## Finish
7. When the builder work is done and the acceptance criteria are met: `close <id>` → status
   `done` (awaiting independent verification). Do **not** set `verified` yourself unless you
   are the verifier team.
8. Comment with the artifact path(s) and a checksum (md5/sha) of the deliverable. "Done"
   without an artifact checksum is an integrity flag.

## Hygiene
- Check for duplicates before `new`: `list [team]` + search titles.
- WIP cap: ~5 in_progress per team. If you're at the cap, finish before picking up.
- `blocked` always requires a reason. `reopen` always requires a reason naming the unmet AC.
- Every ticket needs `--ac` at creation (the CLI enforces this on governed projects; `--force`
  bypasses only when you genuinely can't pre-state criteria).

## If you are the verifier team (role: verifier)
- `show <id>` and check the acceptance criteria against the artifact independently — do not
  trust the builder's claim. Reproduce.
- Pass: `verify <id>` → `verified` (terminal). Fail: `reopen <id> <reason naming unmet AC>`.
- You are read-only by charter: verify or reopen-with-reason. Never build the thing you verify.
