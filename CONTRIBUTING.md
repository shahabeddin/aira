# Contributing to aira

Thanks for helping. aira is deliberately small: **Python 3 standard library only, flat files, no database.**
PRs that add runtime dependencies will be declined; test-only dependencies (pytest) are fine.

## Development

```sh
git clone https://github.com/shahabeddin/aira.git && cd aira
python3 -m pip install pytest
python3 -m pytest -q
```

Tests run the real CLIs in an isolated temp project store (`HOME` and `AGENT_TEAM_PROJECTS_ROOT` are
redirected), so they never touch your own `~/.config/aira` or `projects/`.

## Guidelines

- Keep the CLIs importable-free and stdlib-only; support Python 3.8+.
- Writes must stay atomic (temp file + rename, `flock` for mailboxes).
- If you change behavior, update `BUILD_PROMPT.md` too: it is the canonical from-scratch spec and must stay in sync with the code.
- Add or update a test in `tests/` for every behavior change or bug fix.
- Slash commands live in `.claude/commands/`; templates in `templates/`.

## Pull requests

Branch from `main`, keep PRs focused, and make sure `python3 -m pytest -q` passes.
By contributing you agree your work is released under the repository's MIT license.
