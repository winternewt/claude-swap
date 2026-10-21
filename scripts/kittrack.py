#!/usr/bin/env python3
"""Track the seats kit's releases and move its pin through the gate (docs/TRUST.md, the kit's row).

Nothing outside this repository moves its pin: the kit's lead agreed to leave it to this repo's own
seat (2026-10-20), since each move must pass scripts/kitgate.py before the new copy loads. So this
repo tracks the kit itself.

    kittrack.py check          say what needs the seat, once: a newer release, or a pin moved outside
    kittrack.py watch          the same every --every seconds, each line once (the seat's watcher,
                               [seat.downstream.watch.kit] in .blueprints.toml)
    kittrack.py move [TAG]     the gated move to TAG (default: the newest release), end to end
    kittrack.py move TAG --approved WHERE
                               the same past a gate that said read, once the person approved that
                               reading (WHERE names their answer, e.g. "desk #55"); never past 3 or 4

While the kit's repository is private, with the person its only builder, the person lets this seat move
past a gate that said read once the seat has read and recorded it (2026-10-21, "auto move until kit goes
public"; docs/TRUST.md). check and watch therefore also say when the repository reads without
credentials: from then on each read goes to the person again.

`move` refuses a working tree whose pin differs from HEAD's, or whose files it writes carry changes.
Then: kitgate.py OLD NEW, stopping on any exit but 0; under the client's lock for plugin moves on
this machine (shared with the kit's bin/move-to-tag), the client's three commands; the pin and the
install record read back; kitgate.py NEW NEW --copy on the installed copy, before anything runs it,
a mismatch moving the pin back; the row in SECURITY_AUDIT.md and the version in DOWNSTREAM_NOTES.md;
a commit of the three files; the seat's watchdog restarted on the new copy. Push, the announcement's
reaction and /reload-plugins are left to the seat, and printed.

EXIT STATUS
  0  check/watch: nothing to say · move: moved, or already there
  1  check: a line printed · move: the gate says read; nothing moved
  2  bad usage
  3  unknown: a check could not run, the tree is not ready, or the client failed; nothing moved
     (or moved back)
  4  hard: the gate stopped, or the installed copy differs from its tag (moved back)
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

KIT_URL = "https://github.com/winternewt/agent-seat-blueprints.git"
OWNER_REPO = "winternewt/agent-seat-blueprints"
MARKET, PLUGIN = "agent-seat-blueprints", "seats"
ROOT = Path(__file__).resolve().parent.parent
GATE = Path(__file__).resolve().parent / "kitgate.py"
SETTINGS = ".claude/settings.json"
AUDIT = "SECURITY_AUDIT.md"
NOTES = "docs/seats/DOWNSTREAM_NOTES.md"
NOTES_LINE = re.compile(r"The seat runs on kit v\d+\.\d+\.\d+;")
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
MOVING = ".kitgate/moving"  # while a move runs, the pin differs from HEAD by design: no drift line
QUIET_FAILS = 4  # polls that may fail in a row (an hour at the default) before the watcher complains


class Stop(Exception):
    def __init__(self, rc: int, msg: str):
        super().__init__(msg)
        self.rc = rc


def key(tag: str) -> tuple[int, int, int]:
    m = TAG.fullmatch(tag)
    if not m:
        raise ValueError(f"not a release tag: {tag}")
    return tuple(int(g) for g in m.groups())


def newest(source: str) -> str:
    """The highest release tag on the kit's repository, by number (v0.1.10 is above v0.1.9)."""
    p = subprocess.run(["git", "ls-remote", "--tags", "--refs", source], capture_output=True, text=True)
    if p.returncode:
        raise Stop(3, f"ls-remote {source}: {p.stderr.strip()}")
    tags = [r.rsplit("/", 1)[1] for r in re.findall(r"refs/tags/\S+", p.stdout)]
    tags = [t for t in tags if TAG.fullmatch(t)]
    if not tags:
        raise Stop(3, f"no release tag on {source}")
    return max(tags, key=key)


def ref_of(settings: dict) -> str | None:
    return (settings.get("extraKnownMarketplaces", {}).get(MARKET, {}).get("source", {}).get("ref"))


def pin(root: Path) -> str:
    try:
        ref = ref_of(json.loads((root / SETTINGS).read_text()))
    except (OSError, ValueError) as e:
        raise Stop(3, f"{SETTINGS} cannot be read: {e}") from e
    if not ref or not TAG.fullmatch(ref):
        raise Stop(3, f"{SETTINGS} pins no release tag of {MARKET} (ref {ref!r})")
    return ref


def head_pin(root: Path) -> str | None:
    p = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{SETTINGS}"], capture_output=True, text=True)
    try:
        return ref_of(json.loads(p.stdout)) if p.returncode == 0 else None
    except ValueError:
        return None


def record(root: Path, claude_dir: Path) -> str | None:
    """The version the client's install record names for this clone, None when it has none."""
    try:
        data = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
    except (OSError, ValueError):
        return None
    here = os.path.realpath(root)
    for e in data.get("plugins", {}).get(f"{PLUGIN}@{MARKET}", []):
        if os.path.realpath(e.get("projectPath") or "/nonexistent") == here:
            return e.get("version")
    return None


def drift(root: Path, claude_dir: Path) -> list[str]:
    """The pin moved by something other than `move`: in the tree and not committed, or in the client only."""
    moving = root / MOVING
    if moving.exists() and time.time() - moving.stat().st_mtime < 900:
        return []
    out, now, head = [], pin(root), head_pin(root)
    if head and head != now:
        out.append(f"drift: {SETTINGS} pins {now}, HEAD {head}: the pin moved outside the gate. "
                   f"Run scripts/kitgate.py {head} {now} (and --copy), then commit it or move it back")
    got = record(root, claude_dir)
    if got is not None and got != now[1:]:
        out.append(f"drift: the client's install record for this clone names {got}, the pin {now}: "
                   f"a session started now loads {got}. Check it with scripts/kitgate.py v{got} v{got} --copy "
                   f"{claude_dir}/plugins/cache/{MARKET}/{PLUGIN}/{got}")
    return out


def public(url: str) -> bool:
    """Whether URL reads with no credentials and no user or system git config: the kit gone public."""
    if not url:
        return False
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_ASKPASS="/bin/false", SSH_ASKPASS="/bin/false")
    try:
        return subprocess.run(["git", "ls-remote", url, "HEAD"], capture_output=True, env=env,
                              timeout=60).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def status(root: Path, source: str, claude_dir: Path, public_url: str = KIT_URL) -> list[str]:
    lines = drift(root, claude_dir)
    if public(public_url):
        lines.append(f"the kit's repository {public_url} reads without credentials: it is public, and the "
                     f"person's grant to move past a read has ended (docs/TRUST.md). Put each read to the person")
    now, top = pin(root), newest(source)
    if key(top) > key(now):
        lines.append(f"kit {top} is out, the pin is {now}: scripts/kittrack.py move {top}")
    return lines


def watch(root: Path, source: str, claude_dir: Path, every: float, public_url: str = KIT_URL) -> int:
    said: set[str] = set()
    fails = 0
    while True:
        try:
            lines = status(root, source, claude_dir, public_url)
            fails = 0
            for line in lines:
                if line not in said:
                    print(line, flush=True)
            said = set(lines)
        except Stop as e:
            fails += 1
            if fails == QUIET_FAILS:  # once per streak: the watch plugin delivers every stderr line
                print(f"kit tracking failing {fails} polls in a row: {e}", file=sys.stderr, flush=True)
        time.sleep(every)


# --- the move -------------------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    for s in (p.stdout, p.stderr):
        if s.strip():
            print("  " + s.strip().replace("\n", "\n  "), flush=True)
    return p


def gate(root: Path, a, old: str, new: str, *extra: str) -> int:
    hidden = ["--source", a.source] + (["--mirror", str(a.mirror)] if a.mirror else [])
    return run([sys.executable, str(GATE), old, new, *extra, *hidden], root).returncode


def client(root: Path, a, tag: str) -> None:
    """The client's three commands that move a tracked pin, its marketplace record and its copy."""
    for cmd in (["plugin", "marketplace", "add", f"{a.repo}#{tag}", "--scope", "project"],
                ["plugin", "install", f"{PLUGIN}@{MARKET}", "--scope", "project"],
                ["plugin", "update", f"{PLUGIN}@{MARKET}", "--scope", "project"]):
        if run([a.claude, *cmd], root).returncode:
            raise Stop(3, f"the client failed: {a.claude} {' '.join(cmd)}")
    if pin(root) != tag:
        raise Stop(3, f"{SETTINGS} names {pin(root)} after the client's move, not {tag}")
    if record(root, a.claude_dir) != tag[1:]:
        raise Stop(3, f"the install record names {record(root, a.claude_dir)}, not {tag[1:]}")
    if not copy_of(a, tag).is_dir():
        raise Stop(3, f"the client's copy {copy_of(a, tag)} is missing")


def copy_of(a, tag: str) -> Path:
    return a.claude_dir / "plugins" / "cache" / MARKET / PLUGIN / tag[1:]


def back(root: Path, a, old: str) -> None:
    print(f"moving the pin back to {old}", flush=True)
    try:
        client(root, a, old)
    except Stop as e:
        raise Stop(4, f"the move back to {old} failed too ({e}): the pin and the client's copy are not where "
                      f"the gate passed. Stop the seat and put it to the person") from e


def write_records(root: Path, old: str, new: str, approved: str | None = None) -> None:
    audit = root / AUDIT
    rows = audit.read_text().split("\n")
    head = next(i for i, r in enumerate(rows) if r.startswith("# The seats kit's pin moves"))
    last = max(i for i, r in enumerate(rows) if i > head and re.match(r"\| \d{4}-\d{2}-\d{2} \| v\d", r))
    today = datetime.date.today().isoformat()
    gate_said, why = (("1 read", f"the reading in the row above, approved by the person ({approved})") if approved
                      else ("0 clean", "nothing on the watched paths"))
    rows.insert(last + 1, f"| {today} | {old} → {new} (moved) | {gate_said} | {why} | "
                          f"Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |")
    audit.write_text("\n".join(rows))
    notes = root / NOTES
    text = notes.read_text()
    if not NOTES_LINE.search(text):
        raise Stop(3, f"{NOTES} has no line 'The seat runs on kit vX;' to update")
    notes.write_text(NOTES_LINE.sub(f"The seat runs on kit {new};", text, count=1))


def commit(root: Path, new: str, trailers: list[str], approved: str | None = None) -> None:
    paths = [SETTINGS, AUDIT, NOTES]
    if run(["git", "add", "--", *paths], root).returncode:
        raise Stop(3, "git add failed")
    staged = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout.split()
    if sorted(staged) != sorted(paths):
        raise Stop(3, f"the index holds {staged}, not only {paths}: nothing committed")
    how = f"read, approved by the person ({approved})" if approved else "gated clean"
    msg = f"Move the seats kit pin to {new}: {how}" + ("\n\n" + "\n".join(trailers) if trailers else "")
    if run(["git", "commit", "-q", "-m", msg], root).returncode:
        raise Stop(3, "git commit failed")


def restart(root: Path, a, new: str) -> None:
    copy = copy_of(a, new)
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(copy))
    py = copy / "bin" / "py.sh"  # bin/py before v0.1.86
    wd = ["sh", str(py if py.is_file() else copy / "bin" / "py"), str(copy / "classes" / "base" / "watchdog.py")]
    run([*wd, "stop", a.seat], root, env)
    if run([*wd, "punch-in", a.seat], root, env).returncode:
        raise Stop(3, f"the seat {a.seat} did not punch in on {new}: run /seats:seat {a.seat}")


def move(root: Path, a) -> int:
    old = pin(root)
    if head_pin(root) != old:
        raise Stop(3, f"{SETTINGS} pins {old} and HEAD {head_pin(root)}: settle that drift first")
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", SETTINGS, AUDIT, NOTES],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise Stop(3, f"the files a move writes carry changes:\n{dirty}")
    new = a.tag if a.tag else newest(a.source)
    new = new if new.startswith("v") else f"v{new}"
    key(new)
    if key(new) <= key(old):
        print(f"the pin is {old}; {new} is not newer: nothing to move")
        return 0
    rc = gate(root, a, old, new)
    if rc == 1 and a.approved:
        print(f"the gate said read; the person approved that reading ({a.approved}): moving")
    elif rc:
        print(f"the gate exited {rc}: nothing moved. Read, record and put it to the person "
              f"(docs/seats/DOWNSTREAM_NOTES.md, step 1)")
        return rc
    (root / MOVING).parent.mkdir(parents=True, exist_ok=True)
    (root / MOVING).write_text(f"{old} -> {new}\n")
    try:
        lockdir = a.claude_dir / "plugins"
        lockdir.mkdir(parents=True, exist_ok=True)
        with open(lockdir / ".move-to-tag.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # one plugin move at a time on this machine (the kit's #22)
            try:
                client(root, a, new)
            except Stop:
                back(root, a, old)
                raise
            rc = gate(root, a, new, new, "--copy", str(copy_of(a, new)))
            if rc:
                back(root, a, old)
                raise Stop(4 if rc == 4 else 3, f"the installed copy of {new} did not pass (exit {rc}): moved back to {old}")
        write_records(root, old, new, a.approved)
        commit(root, new, a.trailer, a.approved)
    finally:
        (root / MOVING).unlink(missing_ok=True)
    if not a.no_restart:
        restart(root, a, new)
    how = f"the read approved ({a.approved})" if a.approved else "gated clean"
    print(f"moved: {old} -> {new}, {how}, installed copy == tag, committed. Left for the seat: "
          f"git push origin main; watchdog.py react ID on the announcement, if there is one; "
          f"/reload-plugins for this session's hooks")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["check", "watch", "move"])
    ap.add_argument("tag", nargs="?", help="move: the release to move to (default: the newest)")
    ap.add_argument("--every", type=float, default=900.0, help="watch: seconds between polls")
    ap.add_argument("--seat", default="downstream", help="move: the seat whose watchdog restarts")
    ap.add_argument("--trailer", action="append", default=[], help="move: a line to end the commit message")
    ap.add_argument("--no-restart", action="store_true", help="move: leave the seat's watchdog as it is")
    ap.add_argument("--approved", metavar="WHERE", help="move: the person approved the gate's reading, there")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)  # tests only
    ap.add_argument("--source", default=KIT_URL, help=argparse.SUPPRESS)
    ap.add_argument("--mirror", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--public-url", default=KIT_URL, help=argparse.SUPPRESS)
    ap.add_argument("--repo", default=OWNER_REPO, help=argparse.SUPPRESS)
    ap.add_argument("--claude", default=os.environ.get("CLAUDE_CLI", "claude"), help=argparse.SUPPRESS)
    ap.add_argument("--claude-dir", type=Path,
                    default=Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"),
                    help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.tag and a.cmd != "move":
        ap.error("a tag goes with move only")
    if a.approved and not a.tag:
        ap.error("--approved names the tag the person approved")
    try:
        if a.cmd == "watch":
            return watch(a.root, a.source, a.claude_dir, a.every, a.public_url)
        if a.cmd == "check":
            lines = status(a.root, a.source, a.claude_dir, a.public_url)
            for line in lines:
                print(line)
            return 1 if lines else 0
        return move(a.root, a)
    except Stop as e:
        print(f"kittrack: {e}")
        return e.rc
    except ValueError as e:
        print(f"kittrack: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
