---
description: Spin up or connect to an agent-team project (ticket board + mailbox + web UI)
argument-hint: [project-name]
---

Spin up a multi-agent team project, or connect to an existing one. End result: a project
with teams + roles registered, per-team join instructions, and the web board running with a
URL for the human. **Idempotent** — re-running reconnects to a running server / existing project.

**The session that runs `/team-up` becomes the supervisor (coordinator)** for this project: it
sets its own team identity to `supervisor`, `cd`s into the project working directory, leads the
requirements grilling (step 2), and afterwards runs the `/lead` pass. Other teams are launched as
separate sessions from that workdir (step 4).

This command runs against the `aira` repo. CLIs are at `$AGENT_TEAM_TOOLS/tickets/ticket_cli.py`,
`$AGENT_TEAM_TOOLS/teams_mailbox/mailbox_cli.py`; web UI at `$AGENT_TEAM_TOOLS/tickets/board_server.py`.
If `AGENT_TEAM_TOOLS` is unset, fall back to `./tickets/...` / `./teams_mailbox/...` (cwd = repo root).
Default board port: **8889**.

---

## 1. Pick or create the project

- Project name: the argument (`$1`) if given; else ask the user.
- List existing projects:
  ```
  python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" projects
  ```
- **If the named project already exists:** read its recorded workdir from `projects/<name>/project.json`
  (or `ticket_cli.py projects` — the `->  <path>` suffix). Skip to step 3 (just connect — don't
  recreate teams), but carry the workdir forward to the join card in step 4.
- **If it does not exist:** confirm the name with the user. Then ask **where the project working
  directory is** — the folder where the team will actually work (code, data, notebooks,
  deliverables). This is *separate* from the coordination store (tickets/teams/mailbox), which
  stays under this repo's `projects/<name>/`. Example: project `agent-action-control` → workdir
  `~/work/agent-action-control`. Create the project **and** record the workdir:
  ```
  python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" projects create <name> --workdir <path>
  ```
  This makes the empty coordination store `projects/<name>/{tickets,teams_mailbox,teams}`, writes
  `projects/<name>/project.json` with the workdir, and `mkdir -p`s the workdir if it doesn't
  already exist. (If the user has no workdir yet, suggest a path and create it.)
- **Either way, become the supervisor and enter the workdir:** run **`/set-team supervisor`** (so
  this session's `--by` resolves to `supervisor` for every CLI call), then `cd` into the workdir:
  ```
  cd <workdir>
  ```
  All subsequent work in this session happens from the workdir. If the workdir was just created
  (empty), that's fine — the team populates it.

## 2. Grill the brief, then propose a roster (NEW project only)

You are the coordinator (the **supervisor**) — lead the requirements phase *before* proposing any
roster. A one-line brief like "analyse all_records.csv and predict risk" is **not** enough to staff
a team; turn it into a committed plan first.

**First, interview the brief with `/grill-me`** (an external skill, if installed). Drive the
grilling until the brief is concrete: deliverables, scope, constraints, and success criteria. This
is the **default first step for a new project — do not skip it**, and do not skip it *because* the
prompt is short; a short prompt is the strongest reason to grill. Only skip if the user's brief is
already a concrete, committed plan with clear deliverables and constraints.

**If the brief is an ML problem** — it mentions prediction, classification, risk, scoring,
detection, or learning from data — load `$AGENT_TEAM_TOOLS/docs/ml-problem-checklist.md` and paste
the whole file into the grilling session as the lens, so the interview covers the decisions that
determine whether ML works here: data & labeling, taxonomy, requirements (latency / FPR / recall,
and whether ML adds value at all vs. rules), model selection (traditional / SLM / NN / cascade /
ensemble), features, out-of-distribution evaluation, and the analysis + modeling notebooks. An ML
project typically carves into a **data** lane and a **modeling** lane.

Once the brief is grilled into a committed plan, propose a roster of **lanes + roles**. (Reference
archetypes: "ML research", "full-stack product", "marketing", "solo dev", "security review".)

**Lanes are the primary structure; roles are orthogonal.** A *lane* is a clean ownership
boundary along a real domain axis — frontend / backend, data / modeling. One worker owns
one lane and the deep module behind it. Lanes are **defaults, not dogma**: the coordinator
(you, when proposing) may merge, split, or drop them, and a solo or small project uses **no
lanes** at all. See `docs/lanes-and-modules.md` for the rationale.

Propose a team roster with **lanes + roles** and confirm it with the user before creating
(use AskUserQuestion or list it and ask yes/adjust). The two role questions that matter:

- **Who independently checks the work?** → that team gets `role: verifier`. (Maps to domain:
  `quality` for ML, `qa` for product, `editor` for publishing, `reviewer` for security.)
  **If nobody checks the work, declare NO verifier** — the verify gate stays OFF (fine for
  marketing, solo dev, etc.).
- **Who coordinates / leads?** → `role: coordinator` (runs the `/lead` pass, nudges stalled
  work). Optional. Everyone else is `role: worker` and owns a lane.

Reference archetypes (propose, don't impose):

| User says | Lanes (deep modules) | Roster |
|---|---|---|
| ML research | data (corpus/splits) · modeling (training/eval) | supervisor (coordinator) + data + modeling + quality (verifier) |
| full-stack product | frontend · backend · data | pm (coordinator) + frontend + backend + data + qa (verifier) |
| product w/ PM | frontend · backend | pm (coordinator) + frontend + backend + qa (verifier) |
| marketing | content · social · design | content + social + design — no verifier, no coordinator |
| publishing | writing · editing | writer + editor (verifier) |
| security review | recon · analysis | recon + analyst + reviewer (verifier) |
| solo dev | *(no lanes)* | one worker — no roles, no gate |

**For each lane, write a one-line module interface** into the team `--description` — what the
lane exposes to the other lanes; everything else is internal. This is how lanes surface in the
board's `/teams` page. Example: `data — owns corpus + splits; exposes /datasets/<name> JSONL`.

Then register each team:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" --project <name> teams add <team> --role <verifier|coordinator|worker> [--description "<lane — owns …; exposes …>"]
```
Confirm with:
```
python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" --project <name> teams list
```

## 3. Start the web board (find a free port)

Find the first **free** port from 8889 up and launch the board there (don't assume 8889 is free —
another board may already hold it). A port is free if nothing answers an HTTP request on it.

Try ports 8889, 8890, 8891, … in order. For each candidate port `$p`:
```
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$p/" 2>/dev/null || echo down
```
- **If the curl returns `200`:** something is already serving on `$p` — that port is taken. Skip it
  and try the next port. (Do not reuse another board for this project; launch your own on a free
  port so the URL points at this project's data.)
- **If the curl does not return `200`** (connection refused / `000` / `down`): the port is free.
  Launch the board on it, in the background:
  ```
  python3 "$AGENT_TEAM_TOOLS/tickets/board_server.py" --project <name> --port $p --host 127.0.0.1
  ```
  Run this with the Bash tool in the **background** (`run_in_background: true`). Wait ~1s, then
  re-curl `http://127.0.0.1:$p/`. If it returns `200`, the board is up — **remember `$p`** for the
  join card in step 4. If it still doesn't answer (rare race), kill that process and try `$p+1`.

The board URL is `http://127.0.0.1:$p` (project: `<name>`). If you re-run `/team-up` and a board
for this project is already up on some port, reuse that port instead of starting a second one.

## 4. Give the human the join card

This session is the **supervisor** (coordinator). You are already `cd`'d into the project workdir
(step 1). Print, for the user:

1. **Board URL:** `http://127.0.0.1:$p`  (project: `<name>` — use the port found in step 3)
2. **Workdir:** `<workdir>` — this is where the work happens. You (the supervisor) are already in it.
3. **Per-team join command** (one line per team) — the user opens a **new** terminal per team,
   `cd`s into the workdir, then launches:
   ```
   cd <workdir> && export CLAUDE_TEAM=<team> AGENT_TEAM_PROJECT=<name> AGENT_TEAM_TOOLS="$AGENT_TEAM_TOOLS" && claude
   ```
4. **Bootstrap snippet:** tell each team to paste `templates/CLAUDE_TEAM.md` (with
   `{{TEAM}}`/`{{PROJECT}}`/`{{ROLE}}` filled in, and the **{{LANE}}/{{MODULE}}/{{INTERFACE}}**
   block filled if the project uses lanes — or deleted if not) into its session's CLAUDE.md,
   and to use the `/check-inbox`, `/ticket`, and (if coordinator) `/lead` commands.
5. **Verifier status:** state whether the verify gate is ON (and which team is verifier) or OFF.
6. **Governance:** point the human at `templates/README_GOVERNANCE.md` for the operating rules
   and `docs/lanes-and-modules.md` for how to carve the project into lanes + deep modules.

Keep the final output compact — the board URL, the workdir, and the per-team join lines are the
payload; everything else is one-line pointers.
