#!/usr/bin/env python3
"""Print the Claude Code 5-hour quota window utilization, as a percentage.

Minimal read-only reproduction of what claude-swap does internally
(`oauth.request_usage_data` -> `oauth.build_usage_result`):

    read ~/.claude/.credentials.json  ->  GET /api/oauth/usage  ->  five_hour.utilization

DELIBERATELY READ-ONLY: this never refreshes the token. claude-swap itself
never refreshes the *active* account's credential ("Active accounts are never
refreshed -- Claude Code owns those credentials", oauth.py), because a refresh
can rotate the refresh token and split-brain with a running Claude Code. If the
token is expired, this exits nonzero and tells you to run `claude` instead.

THE USAGE SERVER FIRST. While the dashboard or `cswap auto` runs, claude-swap
answers on $XDG_RUNTIME_DIR/claude-usage.sock (CSWAP_USAGE_SOCKET moves it)
with the active account's last reading, and this script asks it first: no
request, no share of the account's budget. Only when no server listens does it
GET the endpoint itself. --live skips the server.

DON'T POLL THE API HARD. The usage endpoint rate-limits per token; claude-swap's
own notes record that an idle token can trip a 429 from polling alone. Once
every few minutes is plenty.

Usage:
    ./quota_5h.py           # -> "42.7"
    ./quota_5h.py --json    # -> {"pct": 42.7, "resets_at": "...", "countdown": "3h12m"}
    ./quota_5h.py --all     # every window (5h, 7d, per-model), one per line
    ./quota_5h.py --live    # skip the usage server, ask the API

--json adds "source": "server" or "api", and "age_s" for a server reading.

Exit codes: 0 ok | 1 no/expired token | 2 API error | 3 no five_hour in response
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"  # oauth.OAUTH_BETA_HEADER -- required
TIMEOUT_S = 5


def usage_socket() -> Path | None:
    """Mirror claude_swap.usage_server.socket_path (an empty override turns it off)."""
    env = os.environ.get("CSWAP_USAGE_SOCKET")
    if env is not None:
        return Path(env).expanduser() if env else None
    run = os.environ.get("XDG_RUNTIME_DIR")
    return Path(run) / "claude-usage.sock" if run else None


def _iso(epoch: object) -> str | None:
    if not isinstance(epoch, (int, float)):
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def ask_server() -> dict | None:
    """claude-swap's reading in the API's own shape, or None when no server answers for this account.

    Schema 1: connect, read one JSON line, the server closes. A server for
    another config dir is another account's reading, so it is ignored.
    """
    path = usage_socket()
    if path is None or not path.exists() or not hasattr(socket, "AF_UNIX"):
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_S)
    data = b""
    try:
        sock.connect(str(path))
        while chunk := sock.recv(65536):
            data += chunk
        answer = json.loads(data)
    except (OSError, ValueError):
        return None
    finally:
        sock.close()
    if not isinstance(answer, dict) or answer.get("schema") != 1:
        return None
    if answer.get("config_dir") != str(credentials_path().parent.resolve()):
        return None
    active = answer.get("active")
    if not isinstance(active, dict) or active.get("sentinel"):
        return None
    windows = active.get("windows") or {}
    data = {
        key: {"utilization": w["pct"], "resets_at": _iso(w.get("resets_at"))}
        for key, w in windows.items()
        if key in ("five_hour", "seven_day") and isinstance(w, dict)
    }
    data["limits"] = [
        {"scope": {"model": {"display_name": w.get("name")}}, "percent": w.get("pct"),
         "resets_at": _iso(w.get("resets_at"))}
        for w in windows.get("scoped") or []
        if isinstance(w, dict)
    ]
    data["_source"] = "server"
    data["_age_s"] = active.get("age_s")
    return data if "five_hour" in data else None


def credentials_path() -> Path:
    """Mirror claude_swap.paths: $CLAUDE_CONFIG_DIR or ~/.claude, + .credentials.json."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    home = Path(env).expanduser() if env else Path.home() / ".claude"
    return home / ".credentials.json"


def read_access_token() -> str:
    """Return the live OAuth access token, or exit 1 with a reason."""
    path = credentials_path()
    try:
        oauth = json.loads(path.read_text()).get("claudeAiOauth") or {}
    except FileNotFoundError:
        sys.exit(
            f"no credentials at {path}\n"
            "(macOS stores these in the Keychain, not a file -- this script is "
            "Linux/WSL only; on macOS use `cswap --status --json`)"
        )
    except (OSError, ValueError) as e:
        sys.exit(f"could not read {path}: {e}")

    token = oauth.get("accessToken")
    if not token:
        sys.exit(f"no accessToken in {path} -- log in with `claude` first")

    # Advisory only; the 401 handler below is the real check.
    expires_at = oauth.get("expiresAt")
    if isinstance(expires_at, (int, float)):
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        if now_ms >= expires_at:
            sys.exit(
                "access token is expired -- run `claude` to refresh it.\n"
                "(refusing to refresh it here: rotating the active account's "
                "refresh token behind a running Claude Code causes split-brain)"
            )
    return token


def fetch_usage(access_token: str) -> dict:
    """GET the usage endpoint with the exact headers claude-swap sends."""
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": BETA_HEADER,
            "User-Agent": "quota-5h/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit(
                "401 from the usage API -- the access token is no longer valid.\n"
                "Run `claude` to refresh it."
            )
        if e.code == 429:
            retry = (e.headers or {}).get("Retry-After") or "?"
            print(
                f"429 rate-limited by the usage API (Retry-After: {retry}s). "
                "Poll less often.",
                file=sys.stderr,
            )
            sys.exit(2)
        print(f"usage API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(2)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"usage API request failed: {e!r}", file=sys.stderr)
        sys.exit(2)


def countdown(resets_at: str | None) -> str | None:
    """Render an ISO reset timestamp as a compact 'Nh Nm' countdown."""
    if not resets_at:
        return None
    try:
        reset = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    secs = (reset - datetime.now(timezone.utc)).total_seconds()
    if secs <= 0:
        return "due"
    hours, minutes = divmod(int(secs) // 60, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def iter_windows(data: dict):
    """Yield (label, pct, resets_at) for every window the response carries.

    Mirrors oauth.relevant_windows: the always-present five_hour/seven_day
    keys, plus per-model weekly limits from the newer `limits` array.
    """
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        window = data.get(key)
        if isinstance(window, dict) and isinstance(window.get("utilization"), (int, float)):
            yield label, float(window["utilization"]), window.get("resets_at")

    for lim in data.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        scope = lim.get("scope") or {}
        model = scope.get("model") if isinstance(scope, dict) else None
        name = model.get("display_name") if isinstance(model, dict) else None
        pct = lim.get("percent")
        if name and isinstance(pct, (int, float)):
            yield name, float(pct), lim.get("resets_at")


def main() -> None:
    args = sys.argv[1:]
    as_json = "--json" in args
    show_all = "--all" in args

    data = None if "--live" in args else ask_server()
    if data is None:
        data = fetch_usage(read_access_token())
        data["_source"] = "api"
    source, age = data.get("_source"), data.get("_age_s")

    if show_all:
        rows = list(iter_windows(data))
        if as_json:
            print(json.dumps(
                [{"window": w, "pct": p, "resets_at": r, "countdown": countdown(r),
                  "source": source, "age_s": age}
                 for w, p, r in rows],
                indent=2,
            ))
        else:
            for window, pct, resets in rows:
                left = countdown(resets)
                print(f"{window:<10} {pct:5.1f}%" + (f"  (resets in {left})" if left else ""))
        return

    five_hour = data.get("five_hour")
    if not isinstance(five_hour, dict) or not isinstance(
        five_hour.get("utilization"), (int, float)
    ):
        print(
            "response carried no five_hour window "
            f"(keys present: {', '.join(sorted(data)) or 'none'})",
            file=sys.stderr,
        )
        sys.exit(3)

    pct = float(five_hour["utilization"])
    resets = five_hour.get("resets_at")
    if as_json:
        print(json.dumps(
            {"pct": pct, "resets_at": resets, "countdown": countdown(resets),
             "source": source, "age_s": age}
        ))
    else:
        print(f"{pct:.1f}")


if __name__ == "__main__":
    main()
