# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-10-08, extended 2026-10-10 and 2026-10-16
**Versions audited:** `0.26.0`; `0.27.0`, `0.27.1` and `0.27.2` (current stable
on PyPI, see [below](#also-audited-02700272-and-fork-0280b1-at-70dde18));
the fork's `0.27.0b1` at commits `33bb12f` and `5a2211f`, and its `0.28.0b1` at
`70dde18` (git installs, which `cswap upgrade` now installs through the
`audited` tag)
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
  re-checks this list on every run. (From the fork's `5a2211f` a third,
  `usage_server.py`, imports `socket` for a local Unix socket only; see
  [below](#also-audited-fork-0270b1-at-5a2211f).)
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

### Also audited: fork `0.27.0b1` at `5a2211f`

One commit on top of `33bb12f` (3 files under `src/`, +240 / −2; the version
stays `0.27.0b1`). It adds `usage_server.py`, which was read in full, and wraps
the dashboard and `cswap auto` in it:

- **A local listener, not a network one.** While the dashboard or `cswap auto`
  runs, a daemon thread answers on a **Unix socket** (`AF_UNIX`; the module
  has no `AF_INET`): `$XDG_RUNTIME_DIR/claude-usage.sock`, or wherever
  `CSWAP_USAGE_SOCKET` points (empty turns it off). It is bound under
  `umask 0o177`, so the file is `0600`, and a test pins that. It is gone when
  the command exits. No new host, no persistence.
- **What it hands out:** the active account's number, kind, usage percentages,
  reset times, fetch and backoff stamps, and `last_error`, which is one of a
  fixed set of short codes such as `http-429` or `refresh-failed`. It also
  sends `config_dir`, the version and a timestamp. **No token, no email.**
  The same user can already read all of this from `cache/usage.json`.
- **It never fetches for a caller.** Every answer is
  `SnapshotSource.take(store_only=True)`, which passes an empty `fetch` set,
  so no account is eligible (`switcher.py` `_collect_usage_entries`) and no
  request leaves the machine. It caches the answer for 10 s.
- **It reads nothing from the client:** the server sends one line and closes,
  so it parses no input. A stale socket file is replaced only if it is a
  socket (`lstat`, so a symlink is refused). On exit it removes the file only
  if the inode is still its own.
- **New environment reads, local only:** `CSWAP_USAGE_SOCKET` and
  `XDG_RUNTIME_DIR`. They choose a filesystem path, never a request.
- **Caveat:** if `CSWAP_USAGE_SOCKET` points into a shared directory such as
  `/tmp`, other users still cannot connect on Linux, because the socket is
  `0600`. On macOS `XDG_RUNTIME_DIR` is normally unset, so the server is off
  unless that variable is set.

**Build check:** a wheel built from `git archive 5a2211f` with `uv build` holds
exactly `src/claude_swap/` at that commit (42 files, byte-identical). It also
holds `dist-info`, with no `.pth`, the two expected console scripts and the same
`Requires-Dist`. Subprocess modules are still six; `usage_server.py` has none.

### Also audited: `0.27.0`–`0.27.2` and fork `0.28.0b1` at `70dde18`

Upstream tagged three releases. The fork merged upstream at `a410e87`, which
also brings in upstream's `0.28.0b1` version bump (`8fdc89a`, `pyproject.toml`
and `uv.lock` only). It then added one commit of its own, `70dde18`.

**Upstream delta, read in full:** `3a4e5c1` (the base the `5a2211f` audit
covered) `→ 8fdc89a`, 9 files under `src/`, +209 / −70. No new host, no new
request, no new subprocess, no dependency change:

- `credentials.py`, `transfer.py`, `tui/modals.py`: any bare `sk-ant-…` value
  now counts as an API key unless it has an OAuth prefix (`sk-ant-oat`,
  `sk-ant-ort`), so personal `sk-ant-usr…` keys register as keys (#465). This
  changes classification only; the token stays local.
- `switcher.py`: `_write_json` writes through `tempfile.mkstemp`, so the temp
  file is `0600` from the start instead of umask-mode until a later `chmod`
  (a small hardening). Session-credential adoption now **refuses** to write a
  profile's credential into the backup when the profile's identity cannot be
  read, and a switch refuses rather than activate a consumed generation.
- `session.py`: `~/.claude/rules` joins the items symlinked into session
  profiles. For a relative symlinked profile, the Keychain service lookup also
  tries the normalised target path, but only when it is the same directory
  (`os.path.samefile`).
- `paths.py`: follows Claude Code 2.1.299's rule for choosing between
  `.config.json` and `.claude.json`. `usage_store.py`: the alternate-poll pick
  now goes by last attempt, which changes the order only.

**Published `0.27.0`, `0.27.1`, `0.27.2` == their tags.** `redflag.sh <v>
--baseline 0.26.0 --repo . --git-ref v<v>` on each: the PyPI SHA256s verify,
all 41 package files match the tag, the wheel and sdist ship identical code,
the build is stock hatchling with no hooks, `Requires-Dist` is unchanged, and
the hosts are the known ones. Its one red flag on each is the five delta lines
of the `ps` probe in `process_detection.py`, already cleared at `33bb12f`
above. The tags are ancestors of `upstream/main`, so the delta above covers
all three.

| Release | Artifact | SHA256 |
|---|---|---|
| `0.27.0` | wheel | `b57957241282934e91e7a03086301b5ee7dd6233721e163fb161ac48a2aea6d0` |
| `0.27.0` | sdist | `4f1f62bd3dd8d92421ede39b547177ffa1eb4dc70e14dc23a1d583d6c8a9a6ca` |
| `0.27.1` | wheel | `fee45daaf8e653ab66c31ebda10a641d4d2027353cb32839f9f75f449b85f310` |
| `0.27.1` | sdist | `08a80d84d0fad2644ea1145e2d029f79861912965d7f8e35e2c756fece093447` |
| `0.27.2` | wheel | `5d404d8d9c49f3689287ffa4213fd2c55fe683e5a2957abd9856f83bce6c6c9d` |
| `0.27.2` | sdist | `8ca851fd891fb80099579c82f39b12b7ab8fc0664a5ed49d0a9ea01d77100c81` |

**Fork commit `70dde18`: `cswap upgrade` installs the audited commit.**
`update_check.py` no longer runs `uv tool upgrade` / `pipx upgrade`, which
follow PyPI. It runs `uv tool install --force --reinstall 'claude-swap @
git+https://github.com/winternewt/claude-swap.git@audited'` (or `pipx install
--force` with the same URL), as a hardcoded argument array with no shell.
That adds **one literal host, `github.com`**, which `redflag.sh` will report
as unknown on this fork. That is expected. cswap itself sends nothing there:
the URL is an argument to uv or pipx, which fetch the fork's code on an
explicit `cswap upgrade` only. The PyPI version check is unchanged (anonymous
GET to `pypi.org`). Its message now says a newer release is waiting for an
audit.

**Trust moves to the tag.** `@audited` is whatever the tag points at when
`cswap upgrade` runs. Only the fork's owner can move it, and only after an
audit pass. The tag is not a pin: anyone with push access to the fork could
move it. Pin the full sha (below) to rule that out.

**Build check:** a wheel built from `git archive 70dde18` holds exactly
`src/claude_swap/` at that commit (42 files, byte-identical). It also holds
`dist-info`, with no `.pth`, the two expected console scripts and the same
`Requires-Dist`. The network modules are `oauth.py`, `update_check.py` and
`usage_server.py` (`AF_UNIX`). The subprocess modules are still six.

**Also `59d9ffb`, on top of `70dde18`:** `menubar.py` only, +9 / −5. The macOS
framework-build remedy and the missing-`rumps` error now say
`claude-swap[menubar] @` plus the same `AUDITED_SOURCE` string instead of a PyPI
name. They are printed text, not commands cswap runs: no subprocess, no new
host (`github.com` again, through the same constant). A wheel built from
`git archive 59d9ffb` holds exactly `src/claude_swap/` at that commit (42
files, byte-identical, no `.pth`, same `Requires-Dist`).

### To run exactly the audited version

```bash
uv tool install 'claude-swap==0.27.2'      # current stable — verified clean
# or the audited fork commit (pin the full sha; a branch name moves):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@59d9ffbecaaeab3b6f654b6a9b0411fd6b2d0d9f'
# or follow the fork's audited tag (what `cswap upgrade` runs):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@audited'
```

Any commit after `59d9ffb` that touches `src/` or `pyproject.toml` is
**unaudited**. The `audited` tag points at the commit that records this
sentence. Its code is `59d9ffb`'s: the commits after it touch only this file,
`docs/seats/` and `.claude/settings.json`.

**Marker history** (the old commit is recorded here before each move, as the
seat's grant requires):

| Date | `audited` moved from | to | Code audited |
|---|---|---|---|
| 2026-10-16 | (new) | `d138f8d` | `70dde18` |
| 2026-10-16 | `d138f8d` | the commit adding this row | `59d9ffb` |

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

# The seats kit's pin moves

The seats kit (`github.com/winternewt/agent-seat-blueprints`) runs in every session here: its
hooks, its seat watchdog, its quota watcher, and the instructions it gives each session. Its
threat model and standing are in `docs/TRUST.md`. Every move of its pin
(`.claude/settings.json`) passes `scripts/kitgate.py OLD NEW` first, and is recorded below.

What the gate reads: the kit's git source at both tags, from its own bare mirror
(`.kitgate/kit.git`, fetched without `--force`, so a moved tag stops it). It skips the kit's docs,
tests, git hooks and own agent settings, and other roles' instructions. Then it lists four things:

- every network host that is new;
- a change to the runtime dependencies (the kit has none);
- every line that is new on the watched paths. **Hard:** persistence, obfuscation, piping into a
  shell, secrets that are not the kit's own (`.ssh`, `gh`'s hosts file, a keyring, this tool's
  store, a refresh token). **Read:** credentials, network clients, endpoint overrides, a shell given
  a string;
- each new file, and any change to `hooks/hooks.json`, the plugin manifest or an MCP config.

With `--copy`, it also holds the installed copy byte for byte against the tag. Lines are compared
as sets, so a line that only moved between files is not listed again. It does not see a host
built at run time, or a leak through a client and host the kit already uses by a line none of its
patterns name. Its patterns live in this repository, so no kit release can change them.

Calibration, 2026-10-18: of the 29 releases from v0.1.39 to v0.1.67, taken one by one, 15 are
clean, 11 list 1 to 9 lines to read, and 3 stop hard. All 3 hard stops are the same text: the usage
line of the kit's new-machine bootstrap (`curl … | sh -s <seat>`), a script the person runs by hand
on a new machine, which nothing here runs.

| Date | From → to | Gate | What was read | Verdict |
|---|---|---|---|---|
| 2026-10-18 | v0.1.38 → v0.1.67 (adopted before the gate, read after) | 4 hard (the bootstrap's usage text), 33 read, 8 new files | the Zulip driver's new `upload` (a multipart POST to the same server with the seat's own key), `quota.py`'s socket lookup (gains `CSWAP_USAGE_SOCKET`, asked from here as kit #34; the token path and URL are unchanged), the new `trunk-review` agent (sends a `git archive` of tracked files to Cursor's CLI, read-only, only when called), `drivers/github/issues.py`'s base64 (the contents API), `seats.py`'s zuliprc `site=` rewrite (the organisation's rename, #58), `decisions.py`'s secret scrubber, `bin/release`'s `sh -c` (the kit's own release, run in the kit's repo); the 8 new files' headers: none runs here unless called (a new machine's onboarding and its bootstrap, the kit's release, the desk's stats, the lead's plan watcher, a file-inbox watcher, a local report over the message ledger) | Clean for this repo: nothing sends a login anywhere new. The bootstrap text is the person's call (asked 2026-10-18). Installed copy == tag. |
| 2026-10-18 | v0.1.67 → v0.1.68 | 1 read: 33 lines, 5 new files | in full: `classes/base/nightly.py` (night jobs: retro, trunk review, weekly dream; a watcher a repo must declare in `.blueprints.toml`, which this one does not; it starts no model itself); `agents/dream.md` (four model families, three through Cursor's CLI, read-only, on an `outbound-copy` of a public repo, only when called); `bin/outbound-copy` (a `git archive` kept by file type, links and odd names removed: its `sh -c` lines only delete from the copy); `bin/leak-gate` (installs a pre-commit hook only when run, not run here); `scripts/seats.py revive` with `register.py` and `inbox.py` (the admin's tool: resets a pool account's Zulip password through the server's form, reads the reset link from the admin's mailbox and skips one to another host, fetches the key from the same server; not run here); `rules/RETRO.md` (what a retro may quote) | Clean for this repo: everything new either is off here or talks only to hosts the kit already uses. Put to the person 2026-10-18. |
| 2026-10-18 | v0.1.68 → v0.1.69 | 0 clean | nothing on the watched paths | Clean. Waits on the person's word on v0.1.68. |
| 2026-10-18 | v0.1.69 → v0.1.70 | 4 hard: 1 line, plus 2 to read | `bin/onboard:700-722`: the setup line it prints for the person to paste on a new machine (`gh api '…/seating/bootstrap.sh?ref=<commit>' … \| sh -s <seats>`), pinned to the desk's commit; text only, nothing here runs it | Same class as v0.1.67's hard item: the person's call. Put to the person 2026-10-18. |
| 2026-10-18 | v0.1.70 → v0.1.71 | 4 hard: 1 line (`hooks/forge-gate.sh:11` pipes the hook's input into the kit's own `bin/py`, local), plus a new hook and 2 new files to read | in full: the new `PreToolUse` hook on the shell tool (`hooks/forge-gate.sh`, then `classes/base/forge_gate.py`): it reads each command's text, stops at once unless it names `gh`, and checks the text of a `gh` write with `bin/leak-check` and `.githooks/pre-commit.d/10-abs-paths`, both read whole: grep and awk over a temp file, no network, nothing kept. It can deny a session's `gh` write that names an absolute path (this repo keeps no `.leak_words`). The gate skipped `.githooks/` until this pass, now fixed. | Clean for this repo: a guard against leaks, local only. Added to desk #42. |
| 2026-10-19 | v0.1.71 → v0.1.72 | 1 read: 1 new file | in full: `bin/hand` (a seat hands a file to another seat: written into that seat's clone on this machine, under its git directory and never committed; or its text sent as a Zulip direct message through the watchdog; or kept under `$XDG_STATE_HOME`). Run only by a seat that hands something; a handout this seat receives is data from another seat, as a message is | Clean for this repo. Added to desk #42. |
| 2026-10-19 | v0.1.72 → v0.1.73 | 1 read: 2 lines | in full: `drivers/zulip/join.py` (when a new seat's account joins: writes the join time beside its zuliprc, and renames the account to its seat through the same server's API with its own key); run only by `/seats:join` on a new machine | Clean for this repo. Added to desk #42. |
| 2026-10-19 | v0.1.73 → v0.1.74 | 0 clean | nothing on the watched paths | Clean. Waits on desk #42. |
| 2026-10-19 | v0.1.74 → v0.1.75 | 0 clean | nothing on the watched paths | Clean. Covered by desk #42's option 1. |
| 2026-10-19 | v0.1.75 → v0.1.76 | 4 hard: 1 line, the same pipe into the kit's own `bin/py` as v0.1.71's (`hooks/forge-gate.sh:16`, now keeping the output) | in full: `hooks/forge-gate.sh` and `classes/base/forge_gate.py` (#95): the guard also checks the files a `gh gist` or `gh release` call publishes, matches `gh` as a word more widely, and denies the `gh` write when the guard itself cannot run; local only, no network | Clean for this repo: a stricter guard. Explained like v0.1.71's item, so covered by desk #42's option 1. |
| 2026-10-19 | v0.1.76 → v0.1.77 | 1 read: 1 line, 3 new files | the triage class's scripts (`classes/triage/item-next.py`, `triage-archive.py`, `triage-state.py`): headers, imports and every write and subprocess: they read and rewrite the inbox and roadmap documents of the clone they run in, call only `git worktree list`, no network; run only by a triage seat, which this repo has none of | Clean for this repo. Covered by desk #42's option 1. |
| 2026-10-19 | v0.1.77 → v0.1.78 | 1 read: 1 line | `scripts/seats.py mark` (#56): the admin's tool sets a profile field on each pool account, on the team's Zulip, to the seat that holds it; run by the admin seat only | Clean for this repo. Covered by desk #42's option 1. |
| 2026-10-19 | v0.1.78 → v0.1.79 | 0 clean | nothing on the watched paths | Clean. Covered by desk #42's option 1. |
| 2026-10-19 | v0.1.67 → v0.1.79 (the move) | the rows above, v0.1.68 to v0.1.79 | the person's answer on desk #42 ("1*", 2026-10-19 11:26 UTC): option 1, the newest release the gate passed or the seat read clean | Moved. Installed copy == tag (`kitgate.py v0.1.79 v0.1.79 --copy`, exit 0). |
| 2026-10-19 | v0.1.79 → v0.1.80 (moved) | 0 clean | nothing on the watched paths | Moved without asking, per the standing adoption. Installed copy == tag. |
| 2026-10-19 | v0.1.80 → v0.1.81 (moved) | 0 clean | nothing on the watched paths | Moved without asking, per the standing adoption. Installed copy == tag. |
| 2026-10-20 | v0.1.81 → v0.1.82 (moved) | 0 clean | nothing on the watched paths | Moved without asking, per the standing adoption. Installed copy == tag. |
| 2026-10-20 | v0.1.82 → v0.1.84 (moved outside the gate, gated after) | 0 clean | nothing on the watched paths | The pin and the installed copy were moved at 17:49 UTC by the kit's lead seat (agents-kit/lead) with `bin/move-to-tag`, from outside this repo, with no gate and no commit (its message 633402419 says so); the session resumed on it at 17:57. Gated after the fact: clean. Installed copy == tag. v0.1.84 was announced after the move (633402659). The person, 2026-10-21: a one-time mitigation for a pending restart, not the procedure; from now on the seat moves the pin itself (`scripts/kittrack.py`). |
| 2026-10-21 | v0.1.84 → v0.1.85 (read; put to the person, pin stays) | 1 read: 3 `credential` lines in rules/AUTOMODE.md; new files bin/automode, bin/lastlines, classes/builder/release-texts.py, rules/AUTOMODE.md | The four new files whole, and the diffs of classes/base/watchdog.py, bin/claim, classes/base/BASE.md, rules/UNATTENDED.md | Safe here. The credential lines are prose: auto-mode rule text the person pastes by hand into /permissions, naming the admin seat's account revival through the kit's own pool mailbox. bin/automode prints that text and, with --check, reads only the autoMode table of ~/.claude/settings.json (no write, no network); the watchdog now runs that check at each session start. bin/lastlines runs a command and prints its tail. release-texts.py is the builder's watcher, not run here. The watchdog's other changes keep the seat's resume record until a stop succeeds. No new host, nothing reads the logins. One point for the person: the allow entry's (3) lets seats run bin/move-to-tag without asking, once pasted; the kit's lead seat has agreed not to move this pin. |
| 2026-10-21 | v0.1.85 → v0.1.86 (read; added to desk #55, pin stays) | 4 hard: `pipe to shell` in hooks/forge-gate.sh:16; read: 2 `credential` lines, hooks/hooks.json changed, 19 new files | Every renamed script against its old name, the hooks, the diffs of watchdog.py, forge_gate.py, nightly.py, drivers/zulip, drivers/git/watch-remote.sh, scripts/seats.py, bootstrap.sh.in | Safe here. The release gives every `bin/` script its extension (`bin/py` → `bin/py.sh` and so on; the old names stay as symlinks): the 19 new files are those renames, 0 to 24 changed lines each, all the new names. The hard line is the forge gate's existing pipe into the kit's own `bin/py`, now `bin/py.sh` (the same class the person accepted on desk #42); hooks.json changes only that path. The flagged credential lines are prose naming the renamed scripts. Besides: the watchdog says a seat awaiting its onboarding pull request (read-only `git` and `gh pr list`), and the remote watcher fetches once more after a lost race. No new host; nothing reads the logins. |
| 2026-10-21 | v0.1.84 → v0.1.86 (moved) | 4 hard: only `pipe to shell` in hooks/forge-gate.sh:16 (re-gated v0.1.84 → v0.1.86 before the move); the rest read | The two rows above | Moved on the person's answer "1" in this seat's chat (desk #55), by hand with `scripts/kittrack.py`'s own client, copy gate and move-back, since `--approved` never passes a hard stop. Installed copy == tag. |
| 2026-10-21 | v0.1.86 → v0.1.87 (read; put to the person in chat, pin stays) | 1 read: 6 `network` lines in drivers/zulip/plugin.py (and two old ones re-listed in bin/cite-check.py, drivers/claude-code/quota.py); new file commands/away.md | The diffs of drivers/zulip/plugin.py, classes/base/watchdog.py, classes/base/nightly.py, bin/automode.py, bin/claim.sh, classes/desk/deskfile.py, rules/AUTOMODE.md, and commands/away.md whole | Safe here. The network lines are `watchdog.py avatar SEAT --from ID`, run only by hand: the seat's Zulip account fetches the one image attached to a message, from its own server only (any other address is refused; the temporary link is fetched with no key), capped at the avatar size, and sets it as the picture. `/seats:away` and `watchdog.py away` write a time to `$XDG_RUNTIME_DIR/agent-seat-blueprints/leaving`, which turns every seat on the machine unattended at once. The base hook now tells a session that was never given the base to read it. bin/claim counts RM and D ids from their registers. Rule text: the allow entry's items (5) to (7), effective only once the person pastes them; (5) lets seats edit their own repo's CLAUDE.md, AGENTS.md and docs/seats/ without asking. No new host; nothing reads the logins. |
| 2026-10-21 | v0.1.86 → v0.1.87 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-10-23 | v0.1.87 → v0.1.88 (read; moving under the standing grant) | 4 hard: `new network host` with an empty name, the elided `https://...` of a sample line in classes/desk/watch-answers.py:17, which the gate misread (fixed in 644538a; re-gated: 1 read, 53 items: credential and network lines in drivers/leaves/, classes/base/digest.py, agents/consensus.md, skills/mine-sources, uv.lock; 22 new files) | The diffs of watchdog.py, digest.py, forge_gate.py, nightly.py, desk/forge.py, scripts/seats.py, pyproject.toml; drivers/leaves/openrouter-leaf.py and chain.py whole; an Opus reading of every path to an outside model (agents/consensus.md, trunk-review.md, skills consensus, three-leaf, four-leaf, repo-prep, mine-sources, who-holds) | Safe here with one guard. Nothing runs by itself: the hooks are unchanged, and nightly runs only the jobs a repo names (none here). The digest now reads this clone's memory notes locally, to flag paths gone from the repo. The forge gate refuses more desk posts. The OpenRouter leaf refuses without `[consensus] openrouter = true` and reads only `OPENROUTER_API_KEY` from `.env`. The risk: the new consensus skills, typed by the person, send a copy of the repo (HEAD, tracked code and docs) to Cursor, Codex or OpenRouter unless `[repo] outside = "never"`. That gate, and repo-prep's for runs not started by the person, is prose an agent is told to follow. Guard set: `outside = "never"` and a TRUST.md line. No new host; nothing reads the logins. |
| 2026-10-23 | v0.1.87 → v0.1.88 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-10-24 | v0.1.88 → v0.1.89 (hard; put to the person on the desk, pin stays) | 4 hard: 2 `persistence` lines, skills/host-move/SKILL.md:23 and skills/repo-rename/SKILL.md:42; read: credential lines in bin/move-to-tag.py:74, drivers/github/issues.py; network in skills/repo-rename, classes/base/forge_gate.py:36; 7 new files | Both hard lines whole with their skills; the diffs of forge_gate.py, watchdog.py, drivers/zulip/plugin.py, drivers/github/issues.py; drivers/claude-code/move-checkout.py, bin/rename-check.py, classes/desk/rename.py; the new skills' headers | Safe here. The hard lines are prose: the host-move and repo-rename skills tell the person to look for cron lines and systemd units (`crontab -l`), and both skills are the person's to type (`disable-model-invocation: true`). move-checkout.py, run by the person from a plain terminal after every session in the folder has exited, renames a checkout and its client project folder, rewriting transcripts' `cwd` after a backup; standard library only, no network. issues.py gains a contents-API file update through `gh`. The forge gate checks writes to the desk for absolute paths only and lets a `GET` through. The Zulip plugin subscribes only to channels it can see. No new host; nothing reads the logins. |
| 2026-10-25 | v0.1.88 → v0.1.90 (hard; desk #110 now asks for v0.1.90, pin stays) | 2 hard: the same two `persistence` lines as v0.1.89, skills/host-move/SKILL.md:23 and skills/repo-rename/SKILL.md:42; read: credential lines in bin/move-to-tag.py:78, drivers/github/issues.py; network lines in classes/base/watchdog.py (host names, session sockets), bin/hand.sh, skills/repo-rename, classes/base/forge_gate.py:36; hooks/hooks.json changed; 10 new files against v0.1.88 | The v0.1.88 → v0.1.89 read above, then the whole v0.1.89 → v0.1.90 diff outside docs/ and tests/: watchdog.py, drivers/zulip/plugin.py, hooks/hooks.json, bin/hand.sh, bin/move-to-tag.py, bin/mutate.sh, bin/plan-state.sh, bin/rename-check.py, classes/lead/plan-watch.py, drivers/claude-code/move-checkout.py, transcripts.py, watch-version.sh, classes/liaison/watch-upstream.sh, forge_gate.py, BASE.md, rules/AUTOMODE.md, CLAUDE.md, .blueprints.toml, the skills | Safe here. The hook change is a third `base 3` part of the same SessionStart command. Every session now writes a session card (pid, socket, directory) in `$XDG_RUNTIME_DIR`, and `watchdog.py hand-local` posts a handout file's text into a live session through its own socket, as the wakes already do: a same-user channel, which a same-user process already has. The desk team file now serves a stale copy however old when the forge is down (it was a day at most), so a person removed from the team keeps standing until the next good read. The Zulip plugin forwards a person's direct message to another instance of the same seat, on the same server, only where the team file lends machines (it lends none here), and reads the repo's own channel. forge_gate gives a gist, `repo create` or `repo fork` the full check (tighter). move-checkout.py also rewrites `installed_plugins.json` records after a backup, run by the person. watch-version.sh runs `claude --version` hourly, for the kit's liaison seat only. No new host; nothing reads the logins. |
