# Team mailbox — inter-session messaging

Filesystem mailbox for teams of Claude Code sessions to send/receive messages.
Each team has an `inbox.jsonl` (one JSON message per line).

## Layout
```
tmp/teams_mailbox/
  supervisor/inbox.jsonl
  data/inbox.jsonl
  modeling/inbox.jsonl
  quality/inbox.jsonl
```
Message schema: `{"id","from","to","subject","body","ts","read"}`.

## Usage

**Send** (from any session): `/team-send <recipient> <message>`
e.g. `/team-send data Please ingest jackhhao/jailbreak-classification per tmp/SCOUTING_DATA_TASKS_jailbreak_technique.md`

**Receive:** each session periodically polls its own inbox via `/check-inbox`.
Start the poller in a session with:
```
/loop 5m /check-inbox <team>
```
e.g. in the Data session: `/loop 5m /check-inbox data`

For quieter self-paced polling (collapses empty ticks), use dynamic mode:
```
/loop /check-inbox <team>
```

## Per-session identity
Set the team env var in each terminal before launching `claude`, so `/check-inbox` and `/team-send`
know who they are without an argument:
```
export CLAUDE_TEAM=supervisor   # or data | modeling | quality
```
Commands also accept the team as an argument (`/check-inbox supervisor`), which takes precedence.

## How it works
- Polling, not push: a session only acts when `/loop` fires or you prompt it. No headless agents.
- When a session finds unread mail, it handles it in its full interactive context (memory + files),
  writes a reply to the sender's inbox, and marks its own message read.
- Mailbox root override: `export AGENT_TEAM_MAILBOX=/path/to/mailbox`.
