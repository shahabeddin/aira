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
