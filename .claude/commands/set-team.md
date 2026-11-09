---
description: Set this session's team identity (used as --by by the ticket/mailbox CLIs)
argument-hint: <team> [--global]
---

Set this session's team so subsequent ticket/mailbox CLI calls act on its behalf — without
relaunching. The CLIs resolve team in this order: `--by` flag > `CLAUDE_TEAM` env >
`<cwd>/.current_team` > `~/.config/aira/current_team` > `unknown`.

This command writes the on-disk fallback (used when `CLAUDE_TEAM` was **not** set at launch):
- default → `<cwd>/.current_team` (per working directory)
- `--global` → `~/.config/aira/current_team` (default for all sessions on this machine)

## Steps
1. **Team** = `$1` (required). If `--global` is among the args, target the global file.
2. (Optional) Validate it's a known team for the active project:
   `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" --project "$AGENT_TEAM_PROJECT" teams list`
   If it's not listed and you didn't intend to register a new one, say so and stop.
3. Write the file:
   - default: `printf '%s' "<team>" > .current_team`
   - global: `mkdir -p ~/.config/aira && printf '%s' "<team>" > ~/.config/aira/current_team`
4. Confirm: `python3 "$AGENT_TEAM_TOOLS/tickets/ticket_cli.py" whoami` — should print `<team>`.

## Caveat — parallel sessions
`CLAUDE_TEAM` env (set at launch) **wins** over the file, so this command only takes effect when
you launched **without** `CLAUDE_TEAM`. For **parallel sessions** (e.g. 4 teams at once on the
same machine), use the launch-time env var — it's the only session-scoped state:
`export CLAUDE_TEAM=<team> AGENT_TEAM_PROJECT=<project> AGENT_TEAM_TOOLS=<repo> && claude`.
If you launched with `CLAUDE_TEAM` set and want to change teams, relaunch — `/set-team` won't
override it. Use distinct working directories per session to avoid `.current_team` clobbering.
