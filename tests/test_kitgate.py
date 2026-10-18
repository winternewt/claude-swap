"""scripts/kitgate.py: each kind of change it must stop on, against a scratch kit repository."""

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "scripts" / "kitgate.py"

BASE = {
    "hooks/hooks.json": '{"hooks": {}}\n',
    ".claude-plugin/plugin.json": '{"name": "seats", "version": "0.1.0"}\n',
    "pyproject.toml": "[project]\nname = \"kit\"\ndependencies = []\n",
    "classes/base/watchdog.py": 'import urllib.request\nURL = "https://api.anthropic.com/x"\n',
    "docs/NOTES.md": "notes\n",
}


def sh(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def release(kit: Path, tag: str, files: dict[str, str]) -> None:
    for rel, body in files.items():
        (kit / rel).parent.mkdir(parents=True, exist_ok=True)
        (kit / rel).write_text(body)
    sh(kit, "git", "add", "-A")
    sh(kit, "git", "commit", "-q", "--allow-empty", "-m", tag)
    sh(kit, "git", "tag", tag)


@pytest.fixture
def kit(tmp_path):
    k = tmp_path / "kit"
    k.mkdir()
    sh(k, "git", "init", "-q", "-b", "main")
    sh(k, "git", "config", "user.email", "t@example.invalid")
    sh(k, "git", "config", "user.name", "t")
    release(k, "v0.1.0", BASE)
    return k


def gate(kit: Path, old: str, new: str, *extra: str) -> subprocess.CompletedProcess:
    mirror = kit.parent / "mirror.git"
    return subprocess.run([sys.executable, str(GATE), old, new, "--source", str(kit),
                           "--mirror", str(mirror), *extra], capture_output=True, text=True)


def test_a_docs_only_release_is_clean(kit):
    release(kit, "v0.1.1", {"docs/NOTES.md": "more notes, https://new.example.com\n"})
    r = gate(kit, "v0.1.0", "v0.1.1")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("line, label", [
    ('X = "https://collect.example.net/in"\n', "new network host"),
    ("subprocess.run(['crontab', '-'])\n", "persistence"),
    ("exec(codecs.decode(blob, 'rot13'))\n", "obfuscation"),
    ("p = Path.home() / '.ssh' / 'id_ed25519'\n", "foreign secret"),
    ("os.system(fetch() + ' | sh')\n", "pipe to shell"),
])
def test_a_hard_line_stops_the_move(kit, line, label):
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"] + line})
    r = gate(kit, "v0.1.0", "v0.1.1")
    assert r.returncode == 4, r.stdout
    assert label in r.stdout


def test_a_runtime_dependency_stops_the_move(kit):
    release(kit, "v0.1.1", {"pyproject.toml": BASE["pyproject.toml"].replace("[]", '["requests"]')})
    assert gate(kit, "v0.1.0", "v0.1.1").returncode == 4


@pytest.mark.parametrize("files", [
    {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"] + "tok = creds['accessToken']\n"},
    {"hooks/hooks.json": '{"hooks": {"Stop": []}}\n'},
    {"skills/new/SKILL.md": "read the logins\n"},
])
def test_a_watched_change_is_put_to_the_person(kit, files):
    release(kit, "v0.1.1", files)
    assert gate(kit, "v0.1.0", "v0.1.1").returncode == 1


def test_a_line_that_only_moved_is_not_listed_again(kit):
    line = "tok = creds['accessToken']\n"
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"] + line})
    release(kit, "v0.1.2", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"],
                            "drivers/x.py": line})
    r = gate(kit, "v0.1.1", "v0.1.2")
    assert "accessToken" not in r.stdout


def test_a_moved_tag_stops_the_move(kit):
    release(kit, "v0.1.1", {"docs/NOTES.md": "a\n"})
    assert gate(kit, "v0.1.0", "v0.1.1").returncode == 0
    sh(kit, "git", "commit", "-q", "--allow-empty", "-m", "moved")
    sh(kit, "git", "tag", "-f", "v0.1.1")
    r = gate(kit, "v0.1.0", "v0.1.1")
    assert r.returncode == 4 and "tag moved" in r.stdout


def test_an_installed_copy_must_equal_its_tag(kit, tmp_path):
    release(kit, "v0.1.1", {"docs/NOTES.md": "a\n"})
    copy = tmp_path / "copy"
    sh(kit, "git", "worktree", "add", "-q", "--detach", str(copy), "v0.1.1")
    (copy / ".git").unlink()
    (copy / "classes" / "base" / "__pycache__").mkdir()
    (copy / "classes" / "base" / "__pycache__" / "w.pyc").write_bytes(b"x")
    assert gate(kit, "v0.1.0", "v0.1.1", "--copy", str(copy)).returncode == 0
    (copy / "classes" / "base" / "watchdog.py").write_text("import evil\n")
    r = gate(kit, "v0.1.0", "v0.1.1", "--copy", str(copy))
    assert r.returncode == 4 and "differs from the tag" in r.stdout


def test_a_check_that_cannot_run_is_unknown(kit):
    assert gate(kit, "v0.1.0", "v9.9.9").returncode == 3


def test_the_copy_alone_is_checked_with_the_same_tag_twice(kit, tmp_path):
    release(kit, "v0.1.1", {"classes/base/watchdog.py": BASE["classes/base/watchdog.py"] + "tok = creds['accessToken']\n"})
    copy = tmp_path / "copy"
    sh(kit, "git", "worktree", "add", "-q", "--detach", str(copy), "v0.1.1")
    (copy / ".git").unlink()
    assert gate(kit, "v0.1.0", "v0.1.1", "--copy", str(copy)).returncode == 1
    assert gate(kit, "v0.1.1", "v0.1.1", "--copy", str(copy)).returncode == 0
