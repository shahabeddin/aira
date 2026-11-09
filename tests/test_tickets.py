import json


def new_ticket(e, by="boss", team="builder", title="Add widget"):
    r = e.t("--by", by, "new", team, title, "--ac", "widget renders", "--status", "open")
    assert "Created T-0001" in r.stdout
    return "T-0001"


def test_new_ticket_writes_json(aira):
    tid = new_ticket(aira)
    data = json.loads((aira.tickets / f"{tid}.json").read_text())
    assert data["team"] == "builder" and data["status"] == "open"


def test_ac_required_unless_forced(aira):
    r = aira.t("--by", "boss", "new", "builder", "no criteria", check=False)
    assert r.returncode != 0
    aira.t("--by", "boss", "new", "builder", "no criteria", "--force")


def test_happy_path_to_verified(aira):
    tid = new_ticket(aira)
    aira.t("--by", "builder", "status", tid, "in_progress")
    aira.t("--by", "builder", "close", tid)
    assert "done" in aira.t("show", tid).stdout
    aira.t("--by", "qa", "verify", tid)
    data = json.loads((aira.tickets / f"{tid}.json").read_text())
    assert data["status"] == "verified"


def test_only_verifier_can_verify(aira):
    tid = new_ticket(aira)
    aira.t("--by", "builder", "status", tid, "in_progress")
    aira.t("--by", "builder", "close", tid)
    r = aira.t("--by", "builder", "verify", tid, check=False)
    assert r.returncode != 0 and "only qa can verify" in (r.stdout + r.stderr)


def test_reopen_requires_reason_and_returns_to_in_progress(aira):
    tid = new_ticket(aira)
    aira.t("--by", "builder", "status", tid, "in_progress")
    aira.t("--by", "builder", "close", tid)
    assert aira.t("--by", "qa", "reopen", tid, check=False).returncode != 0
    aira.t("--by", "qa", "reopen", tid, "AC", "unmet")
    data = json.loads((aira.tickets / f"{tid}.json").read_text())
    assert data["status"] == "in_progress"


def test_board_lists_active_ticket(aira):
    tid = new_ticket(aira)
    assert tid in aira.t("board").stdout


def test_whoami_precedence_flag_over_env(aira):
    aira.env["CLAUDE_TEAM"] = "builder"
    assert "builder" in aira.t("whoami").stdout
    assert "qa" in aira.t("--by", "qa", "whoami").stdout


def test_whoami_unknown_when_unset(aira):
    assert "unknown" in aira.t("whoami").stdout
