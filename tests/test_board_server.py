import socket
import subprocess
import sys
import time
import urllib.request

from conftest import REPO


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_board_serves_ticket(aira):
    aira.t("--by", "boss", "new", "builder", "Visible on board", "--ac", "a", "--status", "open")
    port = free_port()
    p = subprocess.Popen([sys.executable, str(REPO / "tickets" / "board_server.py"),
                          "--port", str(port), "--host", "127.0.0.1", "--project", "demo"],
                         env=aira.env, cwd=aira.root, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        body = ""
        for _ in range(50):
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/?project=demo", timeout=2).read().decode()
                break
            except OSError:
                time.sleep(0.1)
        assert "Visible on board" in body
    finally:
        p.terminate()
        p.wait(timeout=5)
