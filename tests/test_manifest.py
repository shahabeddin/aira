import re

from conftest import REPO

URL = re.compile(r"^https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/[0-9a-f]{40}/\S+\.md$")


def entries():
    for line in (REPO / "external-skills.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line.split(None, 1)


def test_manifest_entries_are_wellformed_and_pinned():
    rows = list(entries())
    assert rows, "manifest has no entries"
    for row in rows:
        assert len(row) == 2, f"expected '<filename> <url>': {row}"
        name, url = row
        assert name.endswith(".md") and "/" not in name
        assert URL.match(url), f"URL must be pinned to a 40-char commit SHA: {url}"


def test_grill_me_ships_with_its_grilling_dependency():
    names = {r[0] for r in entries()}
    assert {"grill-me.md", "grilling.md"} <= names
