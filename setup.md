# setup.md — install + onboard Aira

> **You were given this file either as a URL (fetched) or a local path (read).** Execute the
> steps below in order. This file **installs** an existing repo and onboards a project — it does
> not build the system from scratch. (To build from scratch instead, use `BUILD_PROMPT.md`.)

You are installing the Aira (`aira`) coordination system (ticket board + inter-team
mailbox + web UI) and onboarding the user to their first project. Work through these steps;
ask the user where a choice is required.

## 1. Locate the tools repo → `TOOLS_DIR`

How did you receive this file?

- **Local path** (the user pasted a filesystem path to this file): the repo is already present.
  Set `TOOLS_DIR` to the directory containing this file. Verify `ls "$TOOLS_DIR/tickets/ticket_cli.py"`
  exists; if not, stop and tell the user the path doesn't look like the repo root.
- **URL** (the user pasted a GitHub URL): ask the user — *"Is the repo already cloned locally?"*
  - **Yes** → ask for the path; set `TOOLS_DIR` to it; verify `tickets/ticket_cli.py` exists.
  - **No** → ask where to install (default `~/aira`); run
    `git clone https://github.com/shahabeddin/aira.git "$TOOLS_DIR"`.

Confirm the repo is present and `TICKET_CLI="$TOOLS_DIR/tickets/ticket_cli.py"` runs:
`python3 "$TICKET_CLI" --help` (should print subcommands including `projects`, `teams`).

## 2. Install the skills — global or local?

Ask the user with AskUserQuestion:

- **Global** — install to `~/.claude/commands/` (works from **any** working directory). Recommended.
- **Local** — install to `<cwd>/.claude/commands/` (only when working in the current directory).

`mkdir -p` the chosen commands dir, then copy these 7 files from `$TOOLS_DIR/.claude/commands/`
into it (overwrite any stale older versions):
`team-up.md`, `set-team.md`, `check-inbox.md`, `ticket.md`, `lead.md`, `team-send.md`, `present.md`

## 2b. Install external skills

Some slash commands are maintained externally and **fetched** (not vendored) at install time.
Read `$TOOLS_DIR/external-skills.txt` — each non-comment line is `<filename> <source-url>`.
For each, download the URL into the **same commands dir** chosen in step 2:
```
curl -fsSL "<url>" -o "<commands_dir>/<filename>"
```
If a fetch fails (network, 404), **warn and continue** — don't abort the whole install; the
built-in commands still work. Report which external skills were installed and their command
names (the filename without `.md`). Example entries: `grilling.md` + `grill-me.md` → install `/grill-me` (a thin entry point that calls the `grilling` skill) — a
skill that interviews a loose idea until it's a committed plan — handy for the coordinator
before turning a brief into tickets.

## 3. Set `AGENT_TEAM_TOOLS`

This env var tells the skills where the CLIs are, so team sessions can run from **any**
directory (not just the repo). Print this for the user:
```
export AGENT_TEAM_TOOLS=<TOOLS_DIR>
```
Then ask: *"Append `export AGENT_TEAM_TOOLS=<TOOLS_DIR>` to your shell profile so it persists?"*
- If yes, append it to `~/.zshrc` (or `~/.bashrc` if they use bash) and tell them to `source` it
  / open a new terminal.

## 4. Onboard a project

Run the **`/team-up`** flow (you just installed it). Either invoke `/team-up`, or perform its
steps inline (read `$TOOLS_DIR/.claude/commands/team-up.md` and follow them). The session running
`/team-up` becomes the **supervisor** (coordinator); the flow:
1. List existing projects (`python3 "$TICKET_CLI" projects`); pick one or create a new one. For a
   new project, ask **where the working directory** is and create it with
   `python3 "$TICKET_CLI" projects create <name> --workdir <path>` (mkdir -p + record in
   `project.json`); `cd` into that workdir. `/set-team supervisor`.
2. **Grill the brief by default** with `/grill-me` (external skill — fetched in step 2b) until
   it's concrete; if it's an ML problem, paste `$TOOLS_DIR/docs/ml-problem-checklist.md` as the
   lens. THEN propose a roster of lanes + roles (verifier = "who independently checks the work?",
   coordinator = the supervisor; everyone else a worker owning a lane; **no verifier → gate
   OFF**), confirm, `teams add` each.
3. Start the board on the **first free port from 8889 up** (curl each candidate; 200 = taken,
   skip; else launch `python3 "$TOOLS_DIR/tickets/board_server.py" --project <name> --port $p
   --host 127.0.0.1` in the background and curl-confirm 200).
4. Print the join card: board URL `http://127.0.0.1:$p`, the workdir, and one
   `cd <workdir> && export CLAUDE_TEAM=<team> AGENT_TEAM_PROJECT=<name> AGENT_TEAM_TOOLS="$TOOLS_DIR" && claude`
   line per team + verifier-gate status + pointer to `templates/CLAUDE_TEAM.md`.

## 5. Final summary

Print, compactly:
- `TOOLS_DIR` and `AGENT_TEAM_TOOLS`
- skills location (global or local) and the 7 built-in commands available, plus any external
  skills fetched from `external-skills.txt` (e.g. `/grill-me`)
- project name, board URL, verifier-gate ON/OFF
- per-team join commands
- a one-line pointer: *"To rebuild the whole system from scratch in a new repo, see
  `BUILD_PROMPT.md`."*
