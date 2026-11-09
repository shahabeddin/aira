# Lanes & deep modules — how to carve an agent-team project

> Guidance, not law. The coordinator decides whether a project uses lanes at all.
> Sources: [*A Philosophy of Software Design*](https://www.goodreads.com/book/show/58665335) (Ousterhout),
> [*Domain-Driven Design*](https://www.goodreads.com/book/show/179133-domain-driven-design) (Evans),
> *Working Effectively with Legacy Code* (Feathers), *The Design of Design* (Brooks),
> *The Pragmatic Programmer* (Hunt & Thomas).

A lane is a clean ownership boundary along a **real domain axis** — frontend / backend,
data / modeling, recon / analysis. One worker owns one lane. A bigger project composes
more lanes; a small or solo project uses none. Carving lanes is a default the coordinator
can merge, split, or drop to fit the work.

## 1. Lanes are defaults, not dogma
- **Principle:** structure the team around real domain boundaries, not org convenience.
- **For a session:** if your project has lanes, you own one and stay in it. If the
  coordinator declared no lanes (solo, marketing, small build), just work the board.

## 2. Deep modules, not shallow work
- **Principle:** a module is deep when it offers rich behavior behind a narrow interface
  (Ousterhout). A worker who only forwards to another lane is a shallow module —
  indirection with no value.
- **For a session:** own a cohesive subsystem end-to-end. If a ticket only asks you to
  relay to another lane, comment "this is a mis-carved lane" and stop — don't staff a
  pass-through.

## 3. Align on the concept before implementing
- **Principle:** resolve the design concept and the inter-lane contract before code
  (Brooks). Ambiguous requirements diverge across lanes into semantic friction.
- **For a session:** before cross-lane work, agree the contract at the seam and pin it in
  the ticket's acceptance criteria. AC verifies the contract, not internal plumbing.

## 4. Ubiquitous vocabulary
- **Principle:** code and tickets use the domain's own words; one canonical term per
  concept everywhere (Evans). No `Manager`/`Helper` synonyms for the same thing across lanes.
- **For a session:** name your lane and your artifacts as the domain names them. If two
  lanes call the same thing by different names, surface it and pick one.

## 5. Combat entropy on every ticket
- **Principle:** the cost of change should stay constant; invest in design daily
  (Hunt & Thomas; Beck). A tactical hack at a lane boundary becomes a permanent liability.
- **For a session:** if a feature fights a lane boundary, refactor the boundary first
  (Boy Scout rule), then apply the change. Leave the seam cleaner than you found it.

---

**Where lanes live in this system:** a lane is recorded as a team with a one-line
*module interface* in its `--description` (what the lane exposes to the others; everything
else is internal). The board's `/teams` page shows it. No special CLI field — lanes ride
on the existing description.
