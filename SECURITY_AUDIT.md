# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-10-08
**Versions audited:** `0.26.0` (current stable — what a plain install gets), and
the fork's `0.27.0b1` at commit `33bb12f` (a git install, see
[below](#also-audited-fork-0270b1-at-33bb12f))
**Previous audits:** 2026-08-14 (`0.25.0`), 2026-06-25 (`0.14.0` / `0.15.0b1`)
**Auditor:** independent review on the `winternewt` fork
**Method:** re-audit of the `0.25.0 → 0.26.0` delta (7 files, +801 / −20 lines
across `src/`, read in full), byte-for-byte verification of the published PyPI
artifacts against the git source, and a review of `scripts/redflag.sh` itself,
which turned out to have missed this release's main change (see
[Blind spots fixed](#blind-spots-fixed-on-2026-10-08)).

---

## Verdict: ✅ Clean, but a past claim is reversed

No phone-home, no data exfiltration, no backdoor. Safe to expose Claude Code
OAuth tokens to `0.26.0`.

**What changed, and it reverses the 0.25.0 report:** that report said
claude-swap "installs no persistence". **0.26.0 can install a macOS
LaunchAgent**, which starts the menu bar at login and restarts it if it
crashes. It is opt-in, behind one explicit command, and nothing installs it for
you. See [Persistence](#persistence-new-in-0260-opt-in-macos-only).

Everything else is the same as 0.25.0: the same 4 endpoints, and the same
dependencies. `oauth.py` and `update_check.py`, the only modules that touch the
network, are unchanged from 0.25.0.

---

## Network surface — unchanged, 4 endpoints, all hardcoded literals

| Endpoint | Method | What is sent | Source |
|---|---|---|---|
| `https://platform.claude.com/v1/oauth/token` | POST | `refresh_token` + Claude Code's public `client_id` — standard OAuth refresh | `oauth.py:18,143` |
| `https://api.anthropic.com/api/oauth/usage` | GET | `Authorization: Bearer <access_token>` — reads usage % | `oauth.py:366` |
| `https://api.anthropic.com/api/oauth/profile` | GET | `Authorization: Bearer <access_token>` — resolves whose token it is | `oauth.py:249` |
| `https://pypi.org/pypi/claude-swap/json` | GET | **nothing** — anonymous, reads only the version field | `update_check.py:16` |

- All four URLs are **hardcoded string constants**, not built from config or
  environment, so they cannot be silently redirected.
- Only **two modules** import network machinery: `oauth.py` and
  `update_check.py`, both with `urllib.request` only. `redflag.sh` now
  re-checks this list on every run.
- Credentials go **only** to Anthropic's two own domains. No `os.environ` value
  feeds any request body, header, or URL.

**New call site, same endpoint:** `add_account` now calls
`fetch_oauth_profile()` to confirm that the token it is about to store belongs
to the account named in `.claude.json`. It refuses on a mismatch and proceeds
on any lookup failure. This is the already-audited `/oauth/profile` request
(Bearer token out, `{uuid, email, organizationUuid}` back), made at one more
moment.

### `truststore`

`cli.py:_use_native_tls()` calls the stock `truststore.inject_into_ssl()`,
delegating certificate verification to the OS-native verifier. This
**strengthens** TLS verification; on any exception it falls back to stdlib
`ssl`. No `verify_mode`, `CERT_NONE`, `check_hostname`, or custom CA bundle
appears anywhere in the tree.

## Persistence (new in 0.26.0, opt-in, macOS only)

`launch_agent.py` (new, 289 lines) runs the menu bar as a launchd LaunchAgent.

- **Only an explicit command installs it:** `cswap menubar --install-service`.
  A full-tree search at the release commit finds exactly three call sites, all
  in `cli.py`, behind `--install-service` / `--uninstall-service` /
  `--service-status`. Plain `cswap menubar`, `cswap upgrade`, first run and
  every other path leave launchd alone.
- **What it writes:** `~/Library/LaunchAgents/com.cswap.menubar.plist` with
  `RunAtLoad` (start at login) and `KeepAlive: {SuccessfulExit: false}`
  (restart on crash, stay down after a deliberate Quit). It runs
  `<path to cswap> menubar` with a fixed `PATH`. Logs go to
  `~/Library/Logs/com.cswap.menubar.{log,err}`. The plist is built with
  `plistlib`, not string formatting.
- **What then runs at every login:** the menu bar, which polls the usage and
  refresh endpoints above on its timer. That is the same network behavior as a
  foreground `cswap menubar`; it just no longer needs a terminal to stay up.
- **How to remove it:** `cswap menubar --uninstall-service` boots the job out
  and deletes the plist.
- **Minor hardening gap:** `launchctl` is resolved through `PATH`, while
  `security` is pinned to `/usr/bin/security`. Exploiting that needs write
  access to a directory early in your own `PATH`, which already means
  same-user compromise. Worth pinning to `/bin/launchctl`; not a backdoor.

The other long-running modes are unchanged from 0.25.0:

- **`cswap auto --loop`** is a foreground polling loop that exits on SIGTERM;
  `--once` ticks and exits.
- **The menu bar**, when not installed as a service, runs only while its
  process lives.
- **Helper threads** are `daemon=True` and in-process.

No systemd unit, cron or `schtasks` entry exists anywhere. On Linux and
Windows, nothing runs that you did not start.

## Process / execution surface

- `subprocess` appears in **five** modules (four in 0.25.0), all with hardcoded
  argument arrays:
  - `macos_keychain.py`: the system `security` CLI.
  - `update_check.py`: `uv`/`pipx upgrade`.
  - `session.py`: launching `claude`, via `os.execvpe` on POSIX.
  - `menubar.py`: `["open", "-R", path]`.
  - **new:** `launch_agent.py`: `["launchctl", "print"|"bootstrap"|"bootout", …]`.
- **No `shell=True` anywhere.** No `eval`, builtin `exec`/`compile`,
  `os.system`, `os.popen`, `pickle`, `marshal`, or `__import__` of
  attacker-controllable input. `ctypes` is used only in two Windows console and
  process-liveness helpers (`printer.py`, `process_detection.py`).
- **The published wheel holds only the package and its `dist-info`:** 40 `.py`
  files, one `.tcss` stylesheet, and metadata. It has no `.pth`, no binaries
  and no extra top-level modules. Its entry points are the two expected
  console scripts (`cswap`, `claude-swap` → `cli:main`).
- **The sdist builds with stock `hatchling.build`,** with no build hooks and
  no `setup.py`.

## New environment reads (local only)

`credentials.py` now reads `CLAUDE_CONFIG_DIR` and
`CLAUDE_SECURESTORAGE_CONFIG_DIR` to pick **which Keychain item** holds the
active profile's credential. Claude Code stores a custom profile's token under
a hashed service name, and reading the fixed default name returned another
account's token. The value only selects a service name passed to the local
`security` CLI. It never reaches a network request, so the "no env value feeds
a request" claim still holds.

## Local state — no tokens on disk beyond the credential store

`usage_store.py` (unchanged) persists per-account usage measurements and
fetch/backoff state to `cache/usage.json`. It stores **no tokens**. Account
identity is carried as `credential_fingerprint()`, a `sha256:`-prefixed
SHA-256 of the refresh token (`oauth.py:43`). Writes go through
`atomic_write_json()`, which inherits the backup directory's `0600`/`0700`
modes.

## Things that continue to raise confidence

- **`/usr/bin/security` is still pinned by absolute path**; secrets pass via
  stdin, never `argv`.
- **Auth env scrubbing** strips five variables before `claude` launches:
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, and
  two file-descriptor variants (`session.py:193`).
- **Account capture got stricter:** `add_account` now refuses a token that
  resolves to a different account, or one that rotated or changed identity
  during the check.
- **Export still strips machine-identity fields** and never auto-uploads;
  import still has explicit path-traversal guards.
- `base64` remains confined to local `.enc` credential backups:
  encode-to-disk and decode-from-disk, not obfuscation.
- No custom `keyring` backend is registered.

## Dependencies — unchanged since 0.25.0

The `Requires-Dist` lines in the 0.25.0 and 0.26.0 wheels are identical.

| Dependency | Scope | Notes |
|---|---|---|
| `textual >=8.2.8,<9` | all platforms | TUI framework; pulls `rich`, `markdown-it-py`, `mdit-py-plugins`, `mdurl`, `linkify-it-py`, `uc-micro-py`, `pygments`, `platformdirs`, `typing-extensions` |
| `truststore >=0.10.4` | all platforms | no transitive deps |
| `keyring >=25.0.0` | **Windows only** | legacy migration only |
| `rumps >=0.4.0` | `menubar` extra, macOS | pulls `pyobjc-framework-cocoa`, `pyobjc-core` |

The dependency tree is still **the largest untrusted input to this package**,
larger than its own code from a supply-chain view. This audit does not read
the dependencies' source.

---

## Supply-chain verification (published artifact == source)

The audited GitHub source is not automatically what `uv tool install` pulls —
the PyPI package is published by `realiti4`, and this is the `winternewt` fork.

### `0.26.0` — published == fork source, byte-for-byte

All **41 files** in the published wheel (40 `.py` + `tui/cswap.tcss`) are
SHA256-identical to `src/claude_swap/` at commit **`0d2176d`**. The **sdist
and wheel ship identical package code**. Both downloads were re-hashed and
matched PyPI's own published digests.

```
wheel  sha256: 0df6b2345888b8cded6473a8d2f0e39c51da20eaa450c70923b22d66a9502cfe
sdist  sha256: f47f013ef6275f360a60000f5864f55697d62bb6b483100c4df7296e46a849d7
```

`0d2176d` is **not** the "version bump" commit (`2d071a7`). The bump was made
on a local branch that lacked the launchd PR (#258, merged on GitHub three
minutes earlier). Twelve seconds after the bump, `0d2176d` merged it in, and
that merge is what was uploaded. Against `2d071a7`, `cli.py` differs and
`launch_agent.py` is missing. The commit actually shipped is the last one
before the next bump (`4b570b2`).

The 0.25.0 artifacts (`c8854305…`, `e665dbd7…`) were re-hashed in the same run
and still match PyPI.

### Also audited: fork `0.27.0b1` at `33bb12f`

Not on PyPI; installed straight from the fork. The `0.26.0 → 33bb12f` delta
(12 files under `src/`, +988 / −94; `pyproject.toml` changes only the version)
was read in full:

- **Network: no change in what is sent or where.** Both network modules
  changed. `oauth.py` gained a local access-token fingerprint helper and a
  stderr redirect. `update_check.py` gained PEP 440 pre-release parsing. They
  have the same 4 hosts and the same requests.
- **New subprocess, local and read-only:** `process_detection.py` runs
  `["ps", "-o", <columns>, "-p", <pid>]` (5 s timeout) to tell a live Claude
  session from a recycled PID. Like `launchctl`, `ps` is found through `PATH`.
- **New credential movement, local only:** after a session-mode Claude exits,
  `switcher.py` copies that session profile's rotated credential into the
  same account's backup. It runs only for the same account, only when the
  profile is newer, and only under cswap's lock. It writes through the
  existing credential store. The copy goes from one local store to another,
  never out.
- **New command `import-usage`:** it reads usage percentages from a local
  JSON file (another machine's `cswap list --json`) and can pause local
  polling for a bounded time. It handles no tokens.
- **Unchanged:** dependencies (same `Requires-Dist`), build backend (stock
  hatchling, no hooks), persistence (only `--install-service`).

**Build check:** a wheel built from `git archive 33bb12f` with `uv build`, the
same path `uv tool install git+…` takes, holds exactly `src/claude_swap/` at
that commit (41 files, byte-identical). It also holds `dist-info`, with no
`.pth` and the two expected console scripts.

### To run exactly the audited version

```bash
uv tool install 'claude-swap==0.26.0'      # current stable — verified clean
# or the audited fork commit (pin the full sha; a branch name moves):
uv tool install --force 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@33bb12f8c72ab2e475cc9646f57aea1ea0779607'
```

Any commit after `33bb12f` that touches `src/` or `pyproject.toml` is
**unaudited**.

---

## Limits of this audit

- Verification is **per-version**. Any future release is unaudited until
  re-checked — the maintainer can publish a new artifact at any time.
- The 0.25.0 → 0.26.0 delta was read line by line. The ~18k lines it builds on
  rest on the 0.25.0 audit's method: risk-bearing modules were read, and the
  rest was cleared by exhaustive grep.
- This clears phone-home / exfiltration / backdoor concerns. It is not a general
  vulnerability assessment of every edge case in credential handling, and it
  does not audit the transitive dependency tree's own source.

## Re-checking future releases

`scripts/redflag.sh` automates this audit for any version. It verifies each
published artifact's SHA256 against PyPI metadata and flags a yanked release.
It checks the artifact shape: nothing outside the package, no `.pth`, entry
points only into the package, a stock sdist build backend with no hooks. It
lists every network host (flagging any outside the Anthropic/PyPI allowlist)
and which modules import network or process machinery. It surfaces exec,
obfuscation and persistence constructs. It diffs the code and the runtime
dependencies against a baseline.

```bash
scripts/redflag.sh                          # latest stable vs your installed version
scripts/redflag.sh 0.27.0                   # a specific version
scripts/redflag.sh 0.27.0 --baseline 0.26.0 # delta vs this audited version
scripts/redflag.sh 0.27.0 --repo . --git-ref <release-commit>
```

**Finding the release commit.** The repo publishes no tags, and the
"version bump" commit is not always what was uploaded: 0.26.0 was bumped at
`2d071a7`, a merge followed, and PyPI got `0d2176d`, the last commit before the
next bump (`4b570b2`). List the bumps with
`git log --oneline -S 'version = "0.27.0"' -- pyproject.toml`. That gives the
commit that set the version and the one that moved past it. Try the first;
if it reports `DIFFERS`, try the second one's parent (`<next-bump>^`).

Exit code `0` = no red flags, `1` = at least one red flag, `2` = bad usage.
A red flag is any of: an unknown host, a new risky construct or dependency vs
the baseline, an odd artifact shape, a SHA256 mismatch, or **a check that could
not run** (no baseline, no sdist, a missing wheel). It is a known-bad-pattern
scanner, not a proof of safety, so always read its output. The delta check
flags *any* added line touching network/exec/env/persistence constructs, so on
most releases it exits `1` on benign code by design. Treat that output as a
review queue, not a verdict.

### Blind spots fixed on 2026-10-08

Re-running the 0.25.0-era script on 0.26.0 showed that it missed a whole new
module. A review of the script's own logic then found these gaps, all now
closed:

| Gap | Effect before the fix |
|---|---|
| Delta used `diff -r`, not `diff -rN` | A **brand-new file** appeared only as "Only in"; none of its lines were scanned. 0.26.0's new `launch_agent.py` (subprocess + LaunchAgent) passed unflagged. |
| Delta dropped every line containing `#` | `subprocess.run(x)  # comment` was invisible. Now only comment-only lines are dropped. |
| `dirname "$(find … \| head -1)"` | When nothing was found, `dirname ""` is `.`: the scan silently ran on the **current directory**, and "baseline not retrievable" could never fire. |
| `--git-ref` + a file absent at that ref | `git show` failed under `pipefail`, and `set -e` killed the script with no message and no verdict. |
| Invalid `--repo`, or `--git-ref` without `--repo` | Silently skipped (a git worktree's `.git` is a file, so `-d .git` failed too). Now exits `2`. |
| Only the package dir was scanned | A `.pth` file, an extra top-level module, or a `.data/` dir in the wheel, and `setup.py`/build hooks in the sdist, all of which execute, were never looked at. |
| All artifacts extracted into one dir | A second wheel overwrote the first one's files, so only one wheel was effectively checked. |
| No dependency check | A new `Requires-Dist` brings in code the script never reads. Now diffed against the baseline. |
| No baseline → delta skipped quietly | Exit `0` with the main check never run. Now a red flag. |
| Narrow construct regexes | `subprocess`, `socket`, `ctypes`, `importlib`, builtin `compile(`, `zlib`, `launchctl`/`LaunchAgents`/`systemctl`/`crontab` were not looked for at all. |
| Missing wheel or sdist → "skipping" | A release without an sdist got no cross-check and no flag. Now a red flag. |
| Verdict said "Safe to install" | Overclaimed. It now says what was checked. |

Still not covered, by design: hosts assembled at runtime rather than written
as a literal URL. The network-module list is the backstop there: a module
joining it needs a read. Also not covered: the dependencies' own source, and
code paths that only a full read would reveal.
