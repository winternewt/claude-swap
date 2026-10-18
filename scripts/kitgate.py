#!/usr/bin/env python3
"""Gate a move of the seats kit's pin (docs/TRUST.md, the kit's row).

The kit's hooks, watchdog, commands, skills and agents run in every session in this repository,
which holds the Claude logins of several accounts. Its releases are cut by agent seats with no
person reading them, so each move of the pin passes this gate first. It reads the kit's git
source, never the installed copy, and lists what changed on the paths a login could leave by.

    kitgate.py OLD NEW              diff the release NEW against OLD (tags, e.g. v0.1.67)
    kitgate.py OLD NEW --copy DIR   also hold the installed copy DIR byte for byte against NEW
    kitgate.py NEW NEW --copy DIR   only that: after the move, before anything runs the copy

The source comes from a bare mirror of the kit's repository, kept in .kitgate/kit.git at this
repository's root (ignored by git) and fetched on every run. A tag that moved since the mirror
saw it is refused by the fetch, which stops the gate.

EXIT STATUS
  0  clean: nothing on the watched paths changed; the pin moves without asking the person.
  1  read: lines on the watched paths changed. The seat reads each listed hunk in full, records
     its verdict in SECURITY_AUDIT.md, and puts the move to the person; the pin stays meanwhile.
  2  bad usage.
  3  unknown: a check could not run. Never a pass: the pin stays.
  4  hard: a new network host, persistence, obfuscation, a credential path outside the kit's
     own, a runtime dependency, a moved tag, or an installed copy that differs from its tag.
     The pin stays; the person decides, with the hunks and the seat's reading.

A clean exit means no known-bad pattern changed, not that the release is safe.
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

KIT_URL = "https://github.com/winternewt/agent-seat-blueprints.git"
ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / ".kitgate" / "kit.git"

# Not loaded by a session here: the kit's own docs, tests, git hooks and agent settings.
SKIP_DIRS = ("docs/", "tests/", ".githooks/", ".cursor/", ".claude/")
SKIP_FILES = {"CLAUDE.md", "AGENTS.md", "README.md", "LICENSE", ".gitattributes", ".gitignore",
              ".cursorignore", ".blueprints.toml", ".leak_allow.template", ".leak_words.template"}
# Instructions a session here loads: the base, this repo's role, and the plugin's skills, commands,
# agents and rules. Another role's priming (the desk's, the lead's) is read only in that seat.
LOADED_MD = ("classes/base/", "classes/downstream/", "skills/", "commands/", "agents/", "rules/",
             "hooks/")
# Files the client adds to an installed copy.
COPY_EXTRA = re.compile(r"(^|/)__pycache__/|\.pyc$|^\.in_use(/|$)")

HARD, READ = "hard", "read"
CATEGORIES = [
    (HARD, "persistence", re.compile(
        r"crontab|systemctl|systemd|\.bashrc|\.bash_profile|\.zshrc|\.profile\b|autostart|"
        r"launchd|LaunchAgents|\.desktop\b|/etc/")),
    (HARD, "obfuscation", re.compile(
        r"\beval\(|\bexec\(|\bmarshal\b|\bpickle\b|__import__|codecs\.decode|"
        r"zlib\.decompress")),
    (HARD, "pipe to shell", re.compile(r"\| *(ba)?sh\b|\| *python")),
    (HARD, "foreign secret", re.compile(
        r"\.ssh\b|\.gnupg|\.aws\b|\.netrc|\.git-credentials|\.config/gh\b|hosts\.yml|"
        r"keyring|keychain|\.claude-swap|claude_swap/|refreshToken|refresh_token")),
    (READ, "credential", re.compile(
        r"credentials|accessToken|claudeAiOauth|oauth|Bearer|Authorization|api_?key|"
        r"zuliprc|\btoken\b|\bsecret\b|\bpassword\b|base64", re.I)),
    (READ, "network", re.compile(
        r"urllib|http\.client|import requests|requests\.\w+\(|httpx|aiohttp|\bsocket\b|"
        r"websocket|smtplib|ftplib|\bcurl\b|\bwget\b|\bnc\b|\bscp\b|rsync|"
        r"\bgh (api|gist|release)\b|cursor-agent")),
    (READ, "endpoint override", re.compile(
        r"(URL|HOST|SITE|ENDPOINT|SERVER|SOCKET)\b.{0,40}environ|environ.{0,40}(URL|HOST|SITE|"
        r"ENDPOINT|SERVER|SOCKET)|\$\{?[A-Z_]*(URL|HOST|ENDPOINT|SERVER)\b")),
    # A plain subprocess call is the kit's everyday tool and is not listed; a shell given a string is.
    (READ, "shell string", re.compile(
        r"os\.system|os\.popen|shell=True|\b(ba)?sh\b\"?,? *\"?-c\b|nohup|setsid")),
]
HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")
WATCHED_FILES = ("hooks/hooks.json", ".claude-plugin/plugin.json", ".mcp.json")


class Unknown(Exception):
    pass


class HardStop(Exception):
    pass


def configure(source: str, mirror: Path) -> None:
    global KIT_URL, MIRROR
    KIT_URL, MIRROR = source, mirror


def git(*args: str, binary: bool = False):
    p = subprocess.run(["git", "--git-dir", str(MIRROR), *args], capture_output=True)
    if p.returncode:
        raise Unknown(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout if binary else p.stdout.decode()


def fetch() -> None:
    if not MIRROR.exists():
        MIRROR.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(["git", "clone", "--bare", "--quiet", KIT_URL, str(MIRROR)],
                           capture_output=True, text=True)
        if p.returncode:
            raise Unknown(f"clone {KIT_URL}: {p.stderr.strip()}")
    # No --force: a tag the mirror holds that now names another commit is refused, and stops us.
    # Not --quiet: it hides the "would clobber existing tag" line this reads.
    p = subprocess.run(["git", "--git-dir", str(MIRROR), "fetch", "--tags", KIT_URL,
                        "+refs/heads/*:refs/heads/*"], capture_output=True, text=True)
    if p.returncode:
        if "would clobber existing tag" in p.stderr:
            raise HardStop(f"a kit tag moved since the mirror saw it:\n{p.stderr.strip()}")
        raise Unknown(f"fetch {KIT_URL}: {p.stderr.strip()}")


def tree(tag: str) -> dict[str, bytes]:
    data = git("archive", "--format=tar", f"refs/tags/{tag}^{{commit}}", binary=True)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar:
            if m.isfile():
                files[m.name] = tar.extractfile(m).read()
            elif m.issym():
                files[m.name] = b"symlink -> " + m.linkname.encode()
    return files


def scanned(path: str) -> bool:
    if path in SKIP_FILES or path.startswith(SKIP_DIRS):
        return False
    return not path.endswith(".md") or path.startswith(LOADED_MD)


def text(blob: bytes) -> str | None:
    try:
        return blob.decode()
    except UnicodeDecodeError:
        return None


def lines(files: dict[str, bytes]):
    for path, blob in files.items():
        if not scanned(path) or (t := text(blob)) is None:
            continue
        for n, line in enumerate(t.splitlines(), 1):
            yield path, n, line.strip()


def matches(files: dict[str, bytes]) -> dict[str, Counter]:
    found = {name: Counter() for _, name, _ in CATEGORIES}
    for _, _, line in lines(files):
        for _, name, rx in CATEGORIES:
            if rx.search(line):
                found[name][line] += 1
    return found


def hosts(files: dict[str, bytes]) -> set[str]:
    return {h.lower().rstrip(".") for _, _, line in lines(files) for h in HOST.findall(line)}


def runtime_deps(files: dict[str, bytes]) -> str:
    m = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)\]", text(files.get("pyproject.toml", b"")) or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def without_version(blob: bytes | None) -> str:
    return re.sub(r'"version"\s*:\s*"[^"]*"', "", text(blob or b"") or "")


def check_copy(new: dict[str, bytes], copy: Path) -> list[str]:
    if not copy.is_dir():
        raise Unknown(f"no installed copy at {copy}")
    problems = []
    seen = set()
    for f in sorted(copy.rglob("*")):
        if not f.is_file() and not f.is_symlink():
            continue
        rel = f.relative_to(copy).as_posix()
        if COPY_EXTRA.search(rel):
            continue
        seen.add(rel)
        got = b"symlink -> " + str(f.readlink()).encode() if f.is_symlink() else f.read_bytes()
        if rel not in new:
            problems.append(f"in the copy, not in the tag: {rel}")
        elif got != new[rel]:
            problems.append(f"differs from the tag: {rel}")
    problems += [f"in the tag, missing from the copy: {p}" for p in sorted(set(new) - seen)]
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--copy", type=Path, help="the installed copy of NEW to hold against its tag")
    ap.add_argument("--source", default=KIT_URL, help=argparse.SUPPRESS)  # tests only
    ap.add_argument("--mirror", type=Path, default=MIRROR, help=argparse.SUPPRESS)
    a = ap.parse_args()
    configure(a.source, a.mirror)
    old_tag, new_tag = (t if t.startswith("v") else f"v{t}" for t in (a.old, a.new))

    try:
        fetch()
        old, new = tree(old_tag), tree(new_tag)
        if subprocess.run(["git", "--git-dir", str(MIRROR), "merge-base", "--is-ancestor",
                           f"refs/tags/{old_tag}^{{commit}}", f"refs/tags/{new_tag}^{{commit}}"]
                          ).returncode:
            print(f"note: {new_tag} does not descend from {old_tag}")
        copy_problems = check_copy(new, a.copy) if a.copy else []
    except HardStop as e:
        print(f"HARD: {e}")
        return 4
    except Unknown as e:
        print(f"UNKNOWN: {e}")
        return 3

    hard, read = [], []
    print(f"kit {old_tag} -> {new_tag}: {sum(1 for p in new if scanned(p))} files scanned "
          f"(docs/, tests/, other roles' instructions and the kit's own agent settings left out)"
          + (f"; installed copy {a.copy} held against the tag" if a.copy else ""))

    for h in sorted(hosts(new) - hosts(old)):
        hard.append(f"new network host: {h}")
    d0, d1 = runtime_deps(old), runtime_deps(new)
    if d0 != d1:
        hard.append(f"runtime dependencies changed: [{d0}] -> [{d1}]")
    hard += copy_problems

    before, after = matches(old), matches(new)
    where: dict[str, list[str]] = {}
    for path, n, line in lines(new):
        where.setdefault(line, []).append(f"{path}:{n}")
    for tier, name, _ in CATEGORIES:
        added = after[name] - before[name]
        for line in sorted(added):
            entry = f"{name}: {', '.join(where.get(line, ['?'])[:3])}\n      {line[:160]}"
            (hard if tier == HARD else read).append(entry)

    for f in WATCHED_FILES:
        o, n = old.get(f), new.get(f)
        if (without_version(o) if f.endswith("plugin.json") else o) != \
           (without_version(n) if f.endswith("plugin.json") else n):
            read.append(f"changed: {f} (what runs by itself, or the plugin's manifest)")
    for f in sorted(p for p in set(new) - set(old) if scanned(p)):
        read.append(f"new file: {f}")

    for label, items in (("HARD", hard), ("READ", read)):
        for item in items:
            print(f"{label}  {item}")
    if hard:
        print(f"hard: {len(hard)} item(s). The pin stays; the person decides.")
        return 4
    if read:
        print(f"read: {len(read)} item(s). Read each in full (git --git-dir {MIRROR} diff "
              f"{old_tag} {new_tag} -- PATH), record a verdict in SECURITY_AUDIT.md, and put "
              f"the move to the person. The pin stays meanwhile.")
        return 1
    print("clean: nothing on the watched paths changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
