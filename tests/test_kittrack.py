"""scripts/kittrack.py: what it reports, and the move end to end against a scratch kit and a stand-in client."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_kitgate import BASE, release, sh

TRACK = Path(__file__).resolve().parent.parent / "scripts" / "kittrack.py"

# Stands in for the client's `claude plugin ...`: moves the pin, and on install/update puts the tag's
# tree in the cache and writes the install record, as the client does. FAKE_TAMPER alters the copy.
FAKE = r'''
import json, os, subprocess, sys
from pathlib import Path
args, root = sys.argv[1:], Path.cwd()
d = Path(os.environ["FAKE_CLAUDE_DIR"])
state = d / "fake_ref"
if args[:3] == ["plugin", "marketplace", "add"]:
    tag = args[3].split("#", 1)[1]
    s = root / ".claude" / "settings.json"
    j = json.loads(s.read_text())
    j["extraKnownMarketplaces"]["agent-seat-blueprints"]["source"]["ref"] = tag
    s.write_text(json.dumps(j, indent=2) + "\n")
    state.write_text(tag)
elif args[:2] in (["plugin", "install"], ["plugin", "update"]):
    tag = state.read_text()
    copy = d / "plugins" / "cache" / "agent-seat-blueprints" / "seats" / tag[1:]
    if not copy.exists():
        copy.mkdir(parents=True)
        tar = subprocess.run(["git", "-C", os.environ["FAKE_KIT"], "archive", tag], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(copy)], input=tar, check=True)
        if os.environ.get("FAKE_TAMPER"):
            with open(copy / "classes" / "base" / "watchdog.py", "a") as f:
                f.write("# tampered\n")
    rec = d / "plugins" / "installed_plugins.json"
    rec.write_text(json.dumps({"version": 2, "plugins": {"seats@agent-seat-blueprints": [
        {"scope": "project", "projectPath": str(root), "version": tag[1:]}]}}))
'''

AUDIT = ("# Audit\n\n# The seats kit's pin moves\n\n| Date | From → to | Gate | What was read | Verdict |\n"
         "|---|---|---|---|---|\n| 2026-10-19 | v0.0.9 → v0.1.0 (moved) | 0 clean | nothing | Moved. |\n")
NOTES = "# Notes\n\n- The seat runs on kit v0.1.0; its watchdog was restarted.\n"


def settings(ref: str) -> str:
    return json.dumps({"extraKnownMarketplaces": {"agent-seat-blueprints": {"source": {
        "source": "github", "repo": "o/kit", "ref": ref}}}}, indent=2) + "\n"


@pytest.fixture
def kit(tmp_path):
    k = tmp_path / "kit"
    k.mkdir()
    sh(k, "git", "init", "-q", "-b", "main")
    sh(k, "git", "config", "user.email", "t@example.invalid")
    sh(k, "git", "config", "user.name", "t")
    release(k, "v0.1.0", BASE)
    return k


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".claude").mkdir(parents=True)
    (r / "docs" / "seats").mkdir(parents=True)
    (r / ".claude" / "settings.json").write_text(settings("v0.1.0"))
    (r / "SECURITY_AUDIT.md").write_text(AUDIT)
    (r / "docs" / "seats" / "DOWNSTREAM_NOTES.md").write_text(NOTES)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@example.invalid")
    sh(r, "git", "config", "user.name", "t")
    sh(r, "git", "add", ".claude/settings.json", "SECURITY_AUDIT.md", "docs/seats/DOWNSTREAM_NOTES.md")
    sh(r, "git", "commit", "-q", "-m", "init")
    return r


def track(kit: Path, repo: Path, *args: str, tamper: bool = False) -> subprocess.CompletedProcess:
    d = kit.parent / "claude"
    d.mkdir(exist_ok=True)
    fake = kit.parent / "fake_claude.py"
    fake.write_text(FAKE)
    wrapper = kit.parent / "claude.sh"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
    wrapper.chmod(0o755)
    env = {"FAKE_CLAUDE_DIR": str(d), "FAKE_KIT": str(kit), "PATH": "/usr/bin:/bin",
           **({"FAKE_TAMPER": "1"} if tamper else {})}
    return subprocess.run([sys.executable, str(TRACK), *args, "--root", str(repo), "--source", str(kit),
                           "--mirror", str(kit.parent / "mirror.git"), "--claude", str(wrapper),
                           "--claude-dir", str(d), "--repo", "o/kit"],
                          capture_output=True, text=True, env=env)


def pinned(repo: Path) -> str:
    return json.loads((repo / ".claude" / "settings.json").read_text())[
        "extraKnownMarketplaces"]["agent-seat-blueprints"]["source"]["ref"]


def test_nothing_newer_says_nothing(kit, repo):
    r = track(kit, repo, "check")
    assert (r.returncode, r.stdout) == (0, ""), r.stdout


def test_the_newest_release_is_named_by_number(kit, repo):
    release(kit, "v0.1.9", {"docs/NOTES.md": "9\n"})
    release(kit, "v0.1.10", {"docs/NOTES.md": "10\n"})
    r = track(kit, repo, "check")
    assert r.returncode == 1 and "kit v0.1.10 is out, the pin is v0.1.0" in r.stdout, r.stdout


def test_a_pin_moved_outside_is_drift(kit, repo):
    (repo / ".claude" / "settings.json").write_text(settings("v0.1.1"))
    release(kit, "v0.1.1", {"docs/NOTES.md": "1\n"})
    r = track(kit, repo, "check")
    assert r.returncode == 1 and "pins v0.1.1, HEAD v0.1.0" in r.stdout, r.stdout


def test_an_install_record_elsewhere_is_drift(kit, repo):
    d = kit.parent / "claude" / "plugins"
    d.mkdir(parents=True)
    (d / "installed_plugins.json").write_text(json.dumps({"plugins": {"seats@agent-seat-blueprints": [
        {"projectPath": "/somewhere/else", "version": "0.0.1"},
        {"projectPath": str(repo), "version": "0.1.5"}]}}))
    r = track(kit, repo, "check")
    assert r.returncode == 1 and "install record for this clone names 0.1.5" in r.stdout, r.stdout


def test_a_clean_release_moves_records_and_commits(kit, repo):
    release(kit, "v0.1.1", {"docs/NOTES.md": "1\n"})
    r = track(kit, repo, "move", "--no-restart", "--trailer", "Co-Authored-By: t <t@example.invalid>")
    assert r.returncode == 0, r.stdout
    assert pinned(repo) == "v0.1.1"
    assert "| v0.1.0 → v0.1.1 (moved) | 0 clean |" in (repo / "SECURITY_AUDIT.md").read_text()
    assert "runs on kit v0.1.1;" in (repo / "docs" / "seats" / "DOWNSTREAM_NOTES.md").read_text()
    log = subprocess.run(["git", "-C", str(repo), "show", "--stat", "--format=%B", "HEAD"],
                         capture_output=True, text=True).stdout
    assert "Move the seats kit pin to v0.1.1: gated clean" in log and "Co-Authored-By: t" in log
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                          capture_output=True, text=True).stdout == ""


def test_a_gate_stop_moves_nothing(kit, repo):
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"]
                            + 'X = "https://collect.example.net/in"\n'})
    r = track(kit, repo, "move", "--no-restart")
    assert r.returncode == 4, r.stdout
    assert pinned(repo) == "v0.1.0" and "nothing moved" in r.stdout
    assert not (kit.parent / "claude" / "fake_ref").exists()  # the client was never called


def test_a_tampered_copy_moves_the_pin_back(kit, repo):
    release(kit, "v0.1.1", {"docs/NOTES.md": "1\n"})
    r = track(kit, repo, "move", "--no-restart", tamper=True)
    assert r.returncode == 4, r.stdout
    assert pinned(repo) == "v0.1.0" and "moved back to v0.1.0" in r.stdout
    assert subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                          capture_output=True, text=True).stdout.count("\n") == 1


def test_a_move_refuses_changed_files(kit, repo):
    release(kit, "v0.1.1", {"docs/NOTES.md": "1\n"})
    (repo / "SECURITY_AUDIT.md").write_text(AUDIT + "| a peer's row |\n")
    r = track(kit, repo, "move", "--no-restart")
    assert r.returncode == 3 and "carry changes" in r.stdout, r.stdout
    assert pinned(repo) == "v0.1.0"


def test_an_approved_reading_moves_and_says_so(kit, repo):
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"] + "import base64\n"})
    r = track(kit, repo, "move", "v0.1.1", "--no-restart")
    assert r.returncode == 1 and pinned(repo) == "v0.1.0", r.stdout
    r = track(kit, repo, "move", "v0.1.1", "--no-restart", "--approved", "desk #9")
    assert r.returncode == 0 and pinned(repo) == "v0.1.1", r.stdout
    assert "| 1 read | the reading in the row above, approved by the person (desk #9) |" in \
        (repo / "SECURITY_AUDIT.md").read_text()


def test_approval_never_passes_a_hard_stop(kit, repo):
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"]
                            + 'X = "https://collect.example.net/in"\n'})
    r = track(kit, repo, "move", "v0.1.1", "--no-restart", "--approved", "desk #9")
    assert r.returncode == 4 and pinned(repo) == "v0.1.0", r.stdout
