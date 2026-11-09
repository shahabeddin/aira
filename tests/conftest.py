"""Shared fixtures: every test runs the real CLIs in an isolated temp project store."""
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
TICKET_CLI = REPO / "tickets" / "ticket_cli.py"
MAILBOX_CLI = REPO / "teams_mailbox" / "mailbox_cli.py"


class Env:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.env = {
            **os.environ,
            "HOME": str(self.root),  # keeps ~/.config/aira out of the real home
            "AGENT_TEAM_PROJECTS_ROOT": str(self.root / "projects"),
            "AGENT_TEAM_PROJECT": "demo",
        }
        for k in ("CLAUDE_TEAM", "AGENT_TEAM_TICKETS", "AGENT_TEAM_MAILBOX"):
            self.env.pop(k, None)

    def _run(self, script, args, check):
        r = subprocess.run([sys.executable, str(script), *args], env=self.env,
                           cwd=self.root, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"{script.name} {args} failed:\n{r.stdout}\n{r.stderr}")
        return r

    def t(self, *args, check=True):
        return self._run(TICKET_CLI, args, check)

    def m(self, *args, check=True):
        return self._run(MAILBOX_CLI, args, check)

    @property
    def tickets(self):
        return self.root / "projects" / "demo" / "tickets"


@pytest.fixture
def aira(tmp_path):
    e = Env(tmp_path)
    e.t("projects", "create", "demo", "--workdir", str(tmp_path))
    e.t("teams", "add", "builder", "--role", "worker")
    e.t("teams", "add", "qa", "--role", "verifier")
    e.t("teams", "add", "boss", "--role", "coordinator")
    return e
