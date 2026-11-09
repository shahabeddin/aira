def test_send_and_list_for_recipient(aira):
    aira.m("--by", "builder", "send", "qa", "hello", "there")
    out = aira.m("--by", "qa", "list").stdout  # defaults to the acting team's inbox
    assert "from=builder" in out and "UNREAD" in out


def test_list_explicit_team_and_unread_filter(aira):
    aira.m("--by", "builder", "send", "qa", "ping")
    msg_id = aira.m("list", "qa").stdout.split()[0]
    aira.m("mark_read", "qa", msg_id)
    assert aira.m("list", "qa", "--unread").stdout.strip() == ""
    assert "read" in aira.m("list", "qa").stdout


def test_reply_all_reaches_original_sender(aira):
    aira.m("--by", "boss", "send", "builder,qa", "kickoff")
    msg_id = aira.m("list", "qa").stdout.split()[0]
    aira.m("--by", "qa", "reply_all", msg_id, "ack")
    assert "re:" in aira.m("list", "boss").stdout
    assert "re:" in aira.m("list", "builder").stdout


def test_read_prints_full_body(aira):
    aira.m("--by", "builder", "send", "qa", "--subject", "S", "the full body")
    msg_id = aira.m("list", "qa").stdout.split()[0]
    out = aira.m("read", "qa", msg_id).stdout
    assert "subject: S" in out and "the full body" in out


def test_send_to_all_excludes_sender(aira):
    aira.m("--by", "boss", "send", "all", "standup")
    assert aira.m("list", "boss").stdout.strip() == ""
    assert "to=[builder, qa]" in aira.m("list", "qa").stdout
