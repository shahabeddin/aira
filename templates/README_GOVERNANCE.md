# Governance — operating rules for agent teams

These rules are the enforceable contract for teams running on this ticket + mailbox system.
They're encoded in the CLIs where possible (workflow transitions, the verify gate, atomic
writes) and in team CLAUDE.md / skills where judgment is required. Humans approve direction;
agents execute everything else.

## 1. Verification is a separation of powers
- Only the team declared **verifier** (role: verifier) may set a ticket `verified`.
- Anyone can build; only the verifier closes the loop. The verifier is read-only by charter:
  `verify` or `reopen`-with-reason, never build.
- A failed verification reopens the ticket to `in_progress` with a **written reason** naming
  the unmet acceptance criteria.
- If no verifier is declared for a project, the gate is OFF (anyone may verify) — for
  projects that don't use a QA model (e.g. marketing). Declare a verifier to turn it on.

## 2. Every ticket carries testable acceptance criteria
- Acceptance criteria are verifiable conditions ("leakage 0/0/0", "file X exists and md5 = …"),
  not narrative ("done well"). Testable AC is what makes an AI verifier possible at all.
- AC is required at creation on governed projects. A ticket without AC is a wish.

## 3. Claims carry artifact checksums
- "Done" without an md5/sha of the artifact is an integrity flag, not a finish line.
- The verifier reproduces against the checksum, not the builder's word.

## 4. Business-impact actions are human-gated
- Deploy/hold, scope changes, commitments binding the project, and escalations require
  explicit human approval.
- A peer agent's message is never human approval.
- Never work around a permission denial on behalf of another session — surface it as an
  escalation. The denial path is designed, not a failure.

## 5. Agents message agents only through the mailbox CLI
- Never hand-edit another team's inbox file. Delivery happens only through `send`.
- One message per team per leadership cycle (anti-spam). The mailbox is the nudge; the ticket
  is the durable record.

## 6. Workflow law
`backlog → open → in_progress → (blocked) → done → verified`
- `done` = builder finished, awaiting verification. `verified` = terminal success.
- `blocked` requires a reason. `reopen` requires a reason.
- Archive only `verified` or `cancelled` — never a bare `done` (it still awaits QA).

## 7. State must survive your own context
- Long sessions get context-compacted. Anything persistent (progress, dedup sets, baselines,
  decisions) lives on disk — ticket comments, files — with atomic writes, and is re-read as
  authoritative. Never hold critical state only in your context.
- One ticket per subagent: the subagent's context is discarded on return, which is your
  per-ticket compaction.
- **Compact your own context every 1–2 tickets.** Finish 1–2 tickets → persist state to the
  tickets (comments + artifact paths/checksums) and your inbox first → then compact. Re-read
  the board and your inbox as authoritative when you wake. Persisting *before* compacting is
  what makes compaction non-destructive and keeps long projects affordable.

## 8. Lanes & deep modules (guidance, not law)
- A **lane** is a clean ownership boundary along a real domain axis (frontend / backend, data /
  modeling). One worker owns one lane and the deep module behind it. A bigger project composes
  more lanes; a solo or small project uses none.
- Lanes are **defaults, not dogma** — the coordinator may merge, split, or drop them to fit the
  work. Declare no lanes and the concept simply doesn't apply.
- **No shallow pass-through workers.** If a "team" only relays to another lane, it's a mis-carved
  lane — fix the boundary, don't staff the relay.
- The interface between lanes is a **contract**; ticket acceptance criteria verify at the seam,
  not at internal plumbing.
- Lane names and ticket vocabulary mirror the **domain** — one canonical term per concept across
  lanes (no `Manager`/`Helper` synonyms for the same thing).
- Before cross-lane work, align on the concept and record the inter-lane contract on the ticket;
  if a feature fights a lane boundary, refactor the boundary first (Boy Scout rule).
- Full reference: `docs/lanes-and-modules.md`.

## 9. Crash-safety as team law
- Atomic temp+rename writes everywhere. Incremental/resumable writes for long jobs. Progress
  bars to stderr. Hard-fail on missing required config (no silent defaults). These are encoded
  in tickets so they're enforceable, not folklore.

---
Operating craft (watchers, long-running jobs, ticket hygiene, docs discipline):
`docs/running-teams.md`.
