"""Usage server: the active account's usage windows on a local Unix socket.

Other tools on the machine that need the active account's usage (a seat
supervisor shedding load on the 5-hour window, a status bar) would
otherwise poll ``/api/oauth/usage`` themselves, on the same small per-account
budget this tool already spends (see ``poll_policy``). Two pollers on one
account trip the 429 regime for both. The server hands them what the store
already holds instead, so the store stays the one checker per account.

Protocol, schema 1: connect, read one JSON line, the server closes. No
request is read. The answer::

    {"schema": 1, "server": "claude-swap", "version": "...",
     "config_dir": "/home/u/.claude",        # whose active credential this is
     "taken_at": 1791655921.0,
     "active": null | {
        "number": "1", "kind": "oauth",
        "sentinel": null | "token expired" | ...,   # replaces the windows
        "fetched_at": ..., "age_s": ..., "backoff_until": ..., "last_error": ...,
        "windows": {"five_hour": {"pct": 38.0, "resets_at": 1791660001.4},
                    "seven_day": {...}, "scoped": [{"name": ..., "pct": ..., "resets_at": ...}]}}}

``resets_at`` is epoch seconds. A client must compare ``config_dir`` with its
own before trusting the numbers: a different dir is a different account.

READ-ONLY AND OFF THE NETWORK. Every answer is a ``store_only`` snapshot: the
server never makes the store fetch. Its hosts (the TUI, ``cswap auto``)
collect on their own schedule, and the answer is as fresh as that.

Where: ``$CSWAP_USAGE_SOCKET`` if set (empty disables the server), else
``$XDG_RUNTIME_DIR/claude-usage.sock``; no runtime dir, or no AF_UNIX, means
no server. The socket is mode 0600. One server per path: a host that finds a
live server there leaves it alone; a dead socket file is replaced.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import stat
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from claude_swap import paths

logger = logging.getLogger(__name__)

SCHEMA = 1
SOCKET_NAME = "claude-usage.sock"
ANSWER_TTL_S = 10.0  # one store read serves every client inside this
CLIENT_TIMEOUT_S = 2.0


def socket_path() -> Path | None:
    """Where the server listens, or None when it should not run."""
    if not hasattr(socket, "AF_UNIX"):
        return None
    env = os.environ.get("CSWAP_USAGE_SOCKET")
    if env is not None:
        return Path(env).expanduser() if env else None
    run = os.environ.get("XDG_RUNTIME_DIR")
    if not run or not Path(run).is_dir():
        return None
    return Path(run) / SOCKET_NAME


def _epoch(resets_at: object) -> float | None:
    if isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool):
        return float(resets_at)
    if not isinstance(resets_at, str):
        return None
    try:
        return datetime.fromisoformat(resets_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _window(w: object) -> dict | None:
    if not isinstance(w, dict) or not isinstance(w.get("pct"), (int, float)):
        return None
    return {"pct": float(w["pct"]), "resets_at": _epoch(w.get("resets_at"))}


def payload(snap, config_dir: Path) -> dict:
    """The schema-1 answer for one ``AccountsSnapshot``."""
    active = next((a for a in snap.accounts if a.is_active), None)
    body: dict | None = None
    if active is not None:
        u = active.usage
        good = u.last_good if isinstance(u.last_good, dict) else {}
        windows: dict = {}
        for key in ("five_hour", "seven_day"):
            w = _window(good.get(key))
            if w is not None:
                windows[key] = w
        scoped = [
            {"name": s.get("name"), **w}
            for s in good.get("scoped") or []
            if isinstance(s, dict) and (w := _window(s)) is not None
        ]
        if scoped:
            windows["scoped"] = scoped
        body = {
            "number": active.number,
            "kind": active.kind,
            "sentinel": u.sentinel,
            "fetched_at": u.fetched_at,
            "age_s": u.age_s,
            "backoff_until": u.backoff_until,
            "last_error": u.last_error,
            "windows": windows,
        }
    from claude_swap import __version__

    return {
        "schema": SCHEMA,
        "server": "claude-swap",
        "version": __version__,
        "config_dir": str(config_dir),
        "taken_at": snap.taken_at,
        "active": body,
    }


def _live(path: Path) -> bool:
    """Whether a server already answers at ``path``."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        s.close()


class UsageServer:
    """Serves store-only snapshots of ``switcher`` on ``path`` from a daemon thread."""

    def __init__(self, switcher, path: Path) -> None:
        from claude_swap.snapshot_source import SnapshotSource

        self.path = path
        self._source = SnapshotSource(switcher)
        self._config_dir = paths.get_claude_config_home().resolve()
        self._sock: socket.socket | None = None
        self._ino: int | None = None
        self._answer: tuple[float, bytes] | None = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Bind and serve; False when another server holds the path or binding failed."""
        try:
            if self.path.exists() or self.path.is_symlink():
                if _live(self.path):
                    logger.info("usage server: one already answers at %s", self.path)
                    return False
                if not stat.S_ISSOCK(self.path.lstat().st_mode):
                    logger.warning("usage server: %s exists and is not a socket; not serving", self.path)
                    return False
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            old = os.umask(0o177)
            try:
                sock.bind(str(self.path))
            finally:
                os.umask(old)
            sock.listen(8)
            self._ino = self.path.stat().st_ino
        except OSError as e:
            logger.warning("usage server: cannot serve at %s: %s", self.path, e)
            return False
        self._sock = sock
        threading.Thread(target=self._serve, name="usage-server", daemon=True).start()
        logger.info("usage server: serving at %s", self.path)
        return True

    def stop(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        with contextlib.suppress(OSError):
            sock.close()
        with contextlib.suppress(OSError):
            if self.path.stat().st_ino == self._ino:  # never unlink a successor's socket
                self.path.unlink()

    def answer(self) -> bytes:
        with self._lock:
            now = time.time()
            if self._answer is None or now - self._answer[0] >= ANSWER_TTL_S:
                snap = self._source.take(store_only=True)
                body = json.dumps(payload(snap, self._config_dir)).encode() + b"\n"
                self._answer = (now, body)
            return self._answer[1]

    def _serve(self) -> None:
        while self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return  # closed by stop()
            with conn:
                conn.settimeout(CLIENT_TIMEOUT_S)
                try:
                    body = self.answer()
                except Exception as e:  # a bad store read must not end the server
                    logger.warning("usage server: snapshot failed: %r", e)
                    body = json.dumps({"schema": SCHEMA, "server": "claude-swap",
                                       "error": f"snapshot failed: {e!r}"}).encode() + b"\n"
                with contextlib.suppress(OSError):
                    conn.sendall(body)


@contextlib.contextmanager
def serving(switcher) -> Iterator[UsageServer | None]:
    """Run the usage server for the duration of a long-lived command, if it should run."""
    path = socket_path()
    server = UsageServer(switcher, path) if path is not None else None
    if server is not None and not server.start():
        server = None
    try:
        yield server
    finally:
        if server is not None:
            server.stop()
