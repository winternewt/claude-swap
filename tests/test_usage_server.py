"""The usage server: the active account's windows on a local socket, store-only."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_swap import usage_server
from claude_swap.models import AccountSnapshot, AccountsSnapshot
from claude_swap.usage_store import UsageEntry


def account(number, active, **usage):
    return AccountSnapshot(
        number=number, email=f"{number}@example.com", org_name="", org_uuid="",
        is_active=active, kind="oauth", switchable=True, usage=UsageEntry(**usage),
    )


GOOD = {
    "five_hour": {"pct": 38.0, "resets_at": "2026-10-10T19:20:01+00:00"},
    "seven_day": {"pct": 10.0, "resets_at": "2026-10-16T22:00:00+00:00"},
    "scoped": [{"name": "Fable", "pct": 4.0, "resets_at": None}, {"name": "bad"}],
}


def snapshot(*accounts):
    return AccountsSnapshot(active_number=None, accounts=accounts, taken_at=1791655921.0)


class FakeSource:
    def __init__(self, snap):
        self.snap, self.calls = snap, []

    def take(self, *, full=False, store_only=False):
        self.calls.append(store_only)
        return self.snap


@pytest.fixture
def sock_dir():
    d = Path(tempfile.mkdtemp(prefix="us"))  # short: AF_UNIX paths stop at 108 bytes
    yield d
    shutil.rmtree(d, ignore_errors=True)


def ask(path: Path) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(path))
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    s.close()
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    return json.loads(data)


def server(path, snap):
    srv = usage_server.UsageServer(SimpleNamespace(), path)
    srv._source = FakeSource(snap)
    return srv


def test_payload_names_the_active_account_only():
    p = usage_server.payload(
        snapshot(account("1", False, last_good={"five_hour": {"pct": 99.0}}),
                 account("2", True, last_good=GOOD, fetched_at=1.0, age_s=2.0)),
        Path("/cfg"),
    )
    assert (p["schema"], p["server"], p["config_dir"]) == (1, "claude-swap", "/cfg")
    a = p["active"]
    assert a["number"] == "2" and a["sentinel"] is None and (a["fetched_at"], a["age_s"]) == (1.0, 2.0)
    assert a["windows"]["five_hour"] == {"pct": 38.0, "resets_at": 1791660001.0}
    assert a["windows"]["seven_day"]["pct"] == 10.0
    assert a["windows"]["scoped"] == [{"name": "Fable", "pct": 4.0, "resets_at": None}]
    assert "email" not in json.dumps(p)


def test_payload_sentinel_and_no_active():
    p = usage_server.payload(snapshot(account("1", True, sentinel="token expired")), Path("/c"))
    assert p["active"]["sentinel"] == "token expired" and p["active"]["windows"] == {}
    assert usage_server.payload(snapshot(account("1", False)), Path("/c"))["active"] is None


def test_serves_store_only_cached_and_private(sock_dir):
    path = sock_dir / "u.sock"
    srv = server(path, snapshot(account("1", True, last_good=GOOD)))
    assert srv.start()
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        a, b = ask(path), ask(path)
        assert a == b and a["active"]["windows"]["five_hour"]["pct"] == 38.0
        assert srv._source.calls == [True]  # store-only, and one read served both inside the TTL
    finally:
        srv.stop()
    assert not path.exists()


def test_one_server_per_path_and_a_dead_socket_replaced(sock_dir):
    path = sock_dir / "u.sock"
    first = server(path, snapshot(account("1", True, last_good=GOOD)))
    assert first.start()
    try:
        assert not server(path, snapshot()).start()  # the live one is left alone
    finally:
        first.stop()
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(path))  # bound, never listening: a crashed host's leftover
    dead.close()
    second = server(path, snapshot(account("1", True, last_good=GOOD)))
    assert second.start()
    try:
        assert ask(path)["active"]["number"] == "1"
    finally:
        second.stop()


def test_a_plain_file_is_never_replaced(sock_dir):
    path = sock_dir / "u.sock"
    path.write_text("mine")
    assert not server(path, snapshot()).start()
    assert path.read_text() == "mine"


def test_a_failed_snapshot_answers_an_error_and_keeps_serving(sock_dir):
    path = sock_dir / "u.sock"
    srv = server(path, snapshot())

    class Broken:
        def take(self, **kw):
            raise RuntimeError("store locked")

    srv._source = Broken()
    assert srv.start()
    try:
        assert "store locked" in ask(path)["error"]
        assert "store locked" in ask(path)["error"]
    finally:
        srv.stop()


def test_socket_path(monkeypatch, sock_dir):
    monkeypatch.setenv("CSWAP_USAGE_SOCKET", "")
    assert usage_server.socket_path() is None
    monkeypatch.setenv("CSWAP_USAGE_SOCKET", str(sock_dir / "x.sock"))
    assert usage_server.socket_path() == sock_dir / "x.sock"
    monkeypatch.delenv("CSWAP_USAGE_SOCKET")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(sock_dir))
    assert usage_server.socket_path() == sock_dir / "claude-usage.sock"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(sock_dir / "missing"))
    assert usage_server.socket_path() is None


def test_serving_disabled_yields_none(monkeypatch):
    monkeypatch.setenv("CSWAP_USAGE_SOCKET", "")
    with usage_server.serving(SimpleNamespace()) as srv:
        assert srv is None


def test_codex_published_quota_over_the_shared_socket(sock_dir, tmp_path, monkeypatch):
    from claude_swap import codex
    from tests.test_codex import _auth, _write_live
    from tests.test_codex_usage_store import _usage

    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    publisher = codex.CodexAccountSwitcher()
    auth = _auth("private@example.test", "private-account-id")
    _write_live(home, auth)
    publisher.add_account(assume_yes=True)
    monkeypatch.setattr(codex, "fetch_codex_usage", lambda *a, **kw: _usage())
    publisher.accounts_snapshot()
    monkeypatch.setattr(codex, "fetch_codex_usage", lambda *a, **kw: pytest.fail("socket fetched"))
    path = sock_dir / "u.sock"
    srv = server(path, snapshot(account("2", True, last_good=GOOD)))
    assert srv.start()
    try:
        result = ask(path)
    finally:
        srv.stop()
    assert result["active"]["number"] == "2"
    section = result["codex"]
    assert section["config_dir"] == str(home.resolve())
    active = section["active"]
    assert active["number"] == "1"
    assert active["windows"]["five_hour"] == {"pct": 12.5, "resets_at": 1800018000}
    assert active["windows"]["seven_day"] == {"pct": 42, "resets_at": 1800604800}
    assert active["credits"]["balance"] == 123.5
    assert active["credit_allowance"]["remaining"] == 450
    assert active["reset_credits"] == {"available": 2, "expires_at": 1800403200}
    assert active["age_s"] >= 0 and active["fetched_at"] <= section["taken_at"]
    for secret in (*auth["tokens"].values(), "private@example.test", "usageGeneration"):
        assert secret not in json.dumps(result)


def test_codex_socket_uses_live_login_and_slot_generation(tmp_path, monkeypatch):
    from claude_swap import codex
    from tests.test_codex import _auth, _write_live

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    switcher = codex.CodexAccountSwitcher()
    auth = _auth("saved@example.test", "saved-account")
    _write_live(tmp_path, auth)
    switcher.add_account(assume_yes=True)
    (switcher.provider_dir / "usage-1.json").write_text(json.dumps({
        "schemaVersion": 1, "number": 1, "slotGeneration": "retired",
        "fetchedAt": 100, "windows": {"weekly": {"usedPercent": 97}},
    }))
    active = usage_server._codex_payload(switcher, 120)["active"]
    assert active["windows"] == {} and active["fetched_at"] is None
    _write_live(tmp_path, _auth("external@example.test", "external-account"))
    assert usage_server._codex_payload(switcher, 120)["active"] is None
    _write_live(tmp_path, {"auth_mode": "api_key", "OPENAI_API_KEY": "fixture-secret"})
    switcher.add_account(assume_yes=True)
    active = usage_server._codex_payload(switcher, 120)["active"]
    assert (active["kind"], active["sentinel"], active["windows"]) == ("api_key", "api key", {})


def test_codex_failure_leaves_claude_available(sock_dir, monkeypatch):
    srv = server(sock_dir / "unused", snapshot(account("2", True, last_good=GOOD)))
    def broken(now):
        raise ValueError("sensitive fixture detail")
    monkeypatch.setattr(srv._codex, "active_cached_usage", broken)
    response = json.loads(srv.answer())
    assert response["active"]["number"] == "2"
    assert response["codex"]["error"] and "sensitive" not in str(response)


@pytest.mark.parametrize("command", ["watch", "auto"])
def test_codex_commands_host_quota_without_migrating_claude(command, sock_dir, monkeypatch):
    from claude_swap import cli, migrations, switcher
    from claude_swap.codex_autoswitch import CodexAutoSwitchEngine
    from claude_swap.tui.codex_watch import CodexWatchApp

    def unexpected_migration(*args):
        pytest.fail("a Codex socket host attempted to migrate Claude storage")

    monkeypatch.setattr(switcher, "migrate_legacy_backup_dir", unexpected_migration)
    monkeypatch.setattr(migrations, "run_migrations", unexpected_migration)
    path = sock_dir / "q.sock"
    monkeypatch.setenv("CSWAP_USAGE_SOCKET", str(path))
    replies = []

    def read_while_running(self):
        replies.append(ask(path))
        return 0

    if command == "watch":
        monkeypatch.setattr(CodexWatchApp, "run", read_while_running)
        cli._codex_command(["watch"])
    else:
        monkeypatch.setattr(CodexAutoSwitchEngine, "run_loop", read_while_running)
        monkeypatch.setattr("signal.signal", lambda *args: None)
        with pytest.raises(SystemExit) as ex:
            cli._codex_command(["auto", "--dry-run", "--json"])
        assert ex.value.code == 0
    assert len(replies) == 1
    assert replies[0]["active"] is None and replies[0]["codex"]["active"] is None
    assert not path.exists()
