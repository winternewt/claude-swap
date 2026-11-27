# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-10-08, extended 2026-10-10, 2026-10-16, 2026-11-04, 2026-11-07, 2026-11-09, 2026-11-14 and 2026-11-26
**Versions audited:** `0.26.0`; `0.27.0`, `0.27.1` and `0.27.2`; `0.28.0` and
`0.29.0`; `0.30.0` and `1.0.0` (see
[below](#also-audited-0300-and-100-and-the-fork-merge-41cc1fb)); `1.1.0` (see
[below](#also-audited-110-and-the-fork-merge-313ec51)); `1.2.0` (the last adopted, see
[below](#also-audited-120-and-the-fork-merge-6aa982f));
the fork's `0.27.0b1` at commits `33bb12f` and `5a2211f`, its `0.28.0b1` at
`70dde18`, its `0.29.0` at `babc945`, and its `1.0.0` at `41cc1fb`, its `1.1.0` at `313ec51`, and its `1.2.0` at `6aa982f` (git installs, which
`cswap upgrade` installs through the `audited` tag)
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

### Also audited: `0.28.0` and `0.29.0`, and the fork merge `babc945`

Upstream tagged two releases. The fork merged the `v0.29.0` tag at `babc945`.
The 21 commits on `upstream/main` past `v0.29.0` are not merged and not audited.

**Upstream delta:** `8fdc89a` (the last upstream commit the `59d9ffb` audit
covered) `→ v0.29.0`, 26 files under `src/`, +2958 / −780. `pyproject.toml`
changes only the version. No new host, no new dependency, no new persistence.

Read in full:

- **`update_check.py`, network.** A uv install now asks `uv pip list
  --outdated --python <this interpreter>` (10 s timeout, run from
  `sys.prefix`, `UV_EXCLUDE_NEWER` stripped) for the newest release, honouring
  the uv receipt's `exclude-newer` cooldown. Non-uv installs still do the
  anonymous GET to `pypi.org`. That means uv, not cswap, now contacts the index
  uv is configured with, the same index `uv tool upgrade` would use. A failed
  lookup is cached for an hour. A new setting, `updates.check`, can switch the
  daily lookup off. After an upgrade, `run_self_upgrade` starts
  `sys.executable -c "import importlib.metadata …"` to report the version that
  landed. Upstream also prints a notice for a release the cooldown hides. It
  advises `uv tool upgrade claude-swap --exclude-newer "0 days"`. **The fork
  drops that notice** (below).
- **`oauth.py`:** a constant for the `"5h"` label only. No request changed.
- **`spawn.py` (new):** on macOS only, `run()` calls `subprocess.run` with an
  absolute path and `close_fds=False`, so CPython takes `posix_spawn` instead
  of `fork`. This avoids a stray libmalloc line (#517). It switches only when
  no descriptor above 2 is inheritable. Otherwise it is plain
  `subprocess.run`. It is used for `ps`, `/usr/bin/security` and one
  `session.py` call, with the same commands as before.
- **`app_bundle.py` (new), macOS only, on `cswap menubar`:** cswap builds
  `/Applications/claude-swap Menubar.app` (or one in the data directory when
  `/Applications` is not writable). The bundle holds a byte copy of the
  running interpreter, a `pyvenv.cfg`, symlinks to the install's
  `lib/python3.X` and the base `libpython`, and an `Info.plist` with
  `com.claude-swap.menubar`. cswap test-runs that interpreter with
  `import claude_swap`, then `os.execv`s into it with the same arguments.
  `CLAUDE_SWAP_NO_BUNDLE` opts out. **This is not persistence.** Nothing
  starts it at login unless the existing opt-in LaunchAgent is installed. It
  does put an app in `/Applications` on first `cswap menubar`.
- **`fsutil.py`, credential writers:** `atomic_write_bytes`/`atomic_write_text`
  replace each module's own temp + rename: the temp is 0600 from `mkstemp`,
  `fchmod` runs on the descriptor, then `fsync`, then rename. Credentials,
  backups, `.enc` files, `sequence.json`, settings, mappings and exports now go
  through it. **One behaviour change:** a destination that is a symlink is
  written *through* to its target (`realpath`, strict), not replaced. Only
  `transfer.py` (an export path the user typed) passes
  `follow_symlinks=False`, so a planted link cannot redirect an export of
  refresh tokens.
- **`credentials.py`:** a 60 s per-slot cache of backup Keychain reads, for
  display and eligibility only. Every read that is POSTed, written or
  activated stays fresh. Inside the Keychain failure cooldown a backup read
  raises without spawning `security`. Tokens stay local.
- **`switcher.py`:** per-account `threshold` and `priority` in `sequence.json`
  (new commands `cswap threshold`, `cswap priority`). The staging files are
  claimed before `O_EXCL` create. A refresh writes the prepared
  live credential to the active store. Nothing leaves the machine.
- **`process_detection.py`, `session.py`, `macos_keychain.py`,
  `launch_agent.py`, `claude_locks.py`, `migrations.py`, `transfer.py`,
  `menubar.py`:** `spawn.run` in place of `subprocess.run`, the shared atomic
  writer, a serialized stale-lock takeover (`<lock>.takeover` directory), a
  session scan that reports an unlistable directory, and a docstring change.

Also read in full, in a second pass the same day (first only swept by grep):

- **`autoswitch.py`** (+758 / −385): the switching engine's decisions. It
  adds per-window lines (`weeklyThreshold`), per-account thresholds, a
  `priority-consume-first` strategy, and a room-based ranking when every
  account is over its lines. It replaces the earlier soonest-reset ranking.
  Every new call out of the module is `switcher.account_policies()` (a read
  of `sequence.json`); the switch itself still goes through the existing
  switcher calls. Its one new write is four health-counter keys
  (`unhealthyTicks`, `idleHoldSince`, `healthAccount`, `healthTickAt`) in its
  own state file, through the existing `_mutate_state`, skipped on a dry run.
  No network, no process, no credential read.
- **`lines.py`** (new): pure arithmetic over `(label, pct, resets_at)`
  triples, no I/O. **`models.py`**: the threshold and priority validators,
  `AccountPolicy`, and the switch rollback through the atomic writer.
  **`poll_policy.py`**: urgent polling judged per window. **`settings.py`**:
  the `weeklyThreshold`, `run.shareHistory` and `updates.check` keys, finite-
  number clamping, and the atomic writer. **`mappings.py`**,
  **`json_output.py`**: the atomic writer and a `threshold` field.
- **`cli.py`**: the `threshold` and `priority` commands (they write
  `sequence.json` through `set_account_threshold` / `set_account_priority`),
  `--weekly-threshold`, and `run.shareHistory` as the default for `cswap
  run`'s existing local history sharing. `updates.check = false` skips the
  version lookup entirely.
- **`tui/app.py`, `tui/autoview.py`, `tui/widgets.py`**: display of the new
  lines and badges only.

**Published `0.28.0`, `0.29.0` == their tags.** `redflag.sh 0.28.0 --baseline
0.27.2 --repo . --git-ref v0.28.0` and `redflag.sh 0.29.0 --baseline 0.28.0
--repo . --git-ref v0.29.0`: the PyPI SHA256s verify. All package files match
the tag (43 and 44). The wheel and sdist ship identical code, the build is
stock hatchling with no hooks, `Requires-Dist` is unchanged, and the hosts are
the known ones. The red flags are the delta lines above (`app_bundle.py`'s
`execv`, `spawn.py`, `update_check.py`'s `uv` and version probes), read in
full.

| Release | Artifact | SHA256 |
|---|---|---|
| `0.28.0` | wheel | `91a67a271b148247242e6ffadb3a2597febf87cde4d7e14ef8df4818744eb902` |
| `0.28.0` | sdist | `d3e796ee44daddeeb342668594d65951788469c94e887148c78eef294d6a2593` |
| `0.29.0` | wheel | `fb30342ea2aa365d706706d02a6c2b5dfe82765c0abaf9a2c4839a9a38450e9e` |
| `0.29.0` | sdist | `175932299b7f627b840ddce63dafc05aecc2d35d168792b4e9f2b94e192a3978` |

**Fork merge `babc945`.** Over `v0.29.0` the fork carries the same changes as
before: `update_check.py`'s `AUDITED_SOURCE` and `UPGRADE_COMMANDS`,
`menubar.py`'s remedy text, `usage_server.py` (unchanged since `audited`) and
its two `serving()` hooks in `cli.py` and `tui/__init__.py`. The merge
conflicted in `update_check.py`. The fork's commands and wording are kept.
Upstream's cooldown notice is not printed, on Windows or after an upgrade,
because it would send the user to `uv tool upgrade`. The function stays,
unused. The tests that pinned the notice now pin its absence. `uv run pytest
-q`: 2954 passed, 7 skipped.

**Build check:** a wheel built from `git archive babc945` holds exactly
`src/claude_swap/` at that commit (45 files, byte-identical), no `.pth`, the
two expected console scripts and the same `Requires-Dist`.

### Also audited: `0.30.0` and `1.0.0`, and the fork merge `41cc1fb`

Read on 2026-11-07, held on the person's desk (#226), **adopted on 2026-11-09**
on their answer, option 1: "I don't care about any Mac-specific behaviors, I
don't have Macs. Autoaccept. Linux affecting ones only." The fork merge is
`41cc1fb` (`git merge --no-ff` of the branch below into main; its `src/`,
`tests/`, `pyproject.toml` and `uv.lock` equal `772a72c`'s). A wheel built from
`git archive 41cc1fb` with `uv build` holds exactly `src/claude_swap/` (46
files, byte-identical), no `.pth`, the two console scripts, and `Requires-Dist`
`textual`, `truststore` and `rumps` (the `menubar` extra) only.

**On this Linux machine** nothing below starts at login, and history sharing
(further down) changes nothing: this machine switches accounts inside the one
`~/.claude` and has no `cswap run` profiles (no `sessions/` folder in the
data directory, checked 2026-11-09), so there is nothing to merge or link.

**Why it was held: the condition the 0.26.0 verdict rested on is gone.** That
verdict accepted the macOS LaunchAgent because it was "opt-in, behind one
explicit command, and nothing installs it for you". Since 1.0.0
(`7a3168d`), plain `cswap menubar` calls `launch_agent.ensure()`.
`ensure()` writes `~/Library/LaunchAgents/com.cswap.menubar.plist` on first
use (`RunAtLoad`, `KeepAlive` on a crash) and bootstraps it.
`--install-service` is no longer needed. The mitigations:

- macOS only, and only with the `menubar` extra installed.
- The command prints that the menu bar starts at login and how to remove it.
- `--foreground` keeps the old behaviour.
- The menu's "Start at login" toggle moves the plist to the data directory,
  where launchd does not scan at login.
- `--uninstall-service`, and `purge`, remove the plist, the logs, launchd's
  disabled override and the wrapper `.app`.

The plist is written 0600 and atomically. It forwards only the proxy, CA and
profile variables (`CLAUDE_CONFIG_DIR`, `CLAUDE_SECURESTORAGE_CONFIG_DIR`,
`XDG_DATA_HOME`). On macOS, `cswap upgrade` now restarts a running menu bar
(`launchctl kickstart -k`) when the build changed. It reads the build from
`direct_url.json` through a fresh interpreter.

**Upstream delta:** `v0.29.0 → v1.0.0`, 22 files under `src/`, +4293 / −726.
`pyproject.toml` drops `keyring` (it was Windows-only, for the retired
Credential Manager → files migration) and moves the classifier to
Production/Stable. No new host, no new dependency.

Read in full:

- **`oauth.py`, network.** A new header probe, `request_usage_via_probe`.
  It sends a POST to `https://api.anthropic.com/v1/messages`: a 1-token Haiku
  request carrying the account's bearer token, and reads the
  `anthropic-ratelimit-unified-*` response headers. This is a new kind of
  request (it spends a little inference), but it goes to a known host. It runs
  only when the setting `usage.headerProbe` is true (default false; a non-bool
  is rejected) AND the account is a setup-token (no refresh token, scopes
  exactly `user:inference`). It has one caller. The rest of the file is
  stricter parsing of usage responses (`_InvalidUsageResponse`), with no new
  request.
- **`subscription.py` (new), network.** A GET to
  `https://api.anthropic.com/api/oauth/profile` with an already valid access
  token. It never refreshes a token. It keeps five organization fields, and
  only when the response's account and organization UUIDs match the slot. The
  cache is `subscription_plans.json`, written atomically under a lock. A
  successful read is paced at once per 6 h per account, a failed one at 15 min
  or more. A pass scoped to one slot still reads every slot that is due, and
  the token goes only to Anthropic.
- **`launch_agent.py`** (+701), the persistence above, read whole at
  `v1.0.0`. Its process calls: `launchctl
  print/print-disabled/bootstrap/bootout/kickstart/enable`, `sfltool dumpbtm`
  (read only, to see the System Settings switch) and `ps -o etime`. Each is a
  fixed argv, with no shell and no user text.
- **`update_check.py`:** `install_identity` / `_restart_menubar_if_rebuilt`
  (above). The fork keeps `UPGRADE_COMMANDS` and still drops the cooldown
  notice.
- **`app_bundle.py`:** `remove()` deletes the wrapper `.app` from either home,
  for uninstall.
- **`credentials.py`:** a file-mode pin is lifted once `.credentials.json` is
  gone, which re-asks the Keychain under a new lock. `.enc` and stash reads go
  by bytes. No write path changed.
- **`fsutil.py`:** link helpers. `make_dir_link` makes a symlink, or a
  junction on Windows. `remove_link` removes the link, never its target.
  `is_link` also counts junctions. The 0.29.0 claim stands: `transfer.py`'s
  export is the only `follow_symlinks=False` writer.
- **`migrations.py`:** the Windows keyring migration is retired, and the macOS
  one reads and deletes legacy items through `security`. **`transfer.py`:**
  clearer import errors only.
- **`menubar.py`:** a health row, engine-stopped events and the Start-at-login
  toggle (`set_start_at_login` moves the plist only). The settings file is
  written atomically, 0600.
- **`session.py`, `switcher.py`, `cli.py`,** read whole hunk by hunk by a
  second reader (Opus) at the seat's request:
  - **`session.py`:** no network. The `claude` exec is unchanged.
  - **`session.py` links:** history sharing builds symlinks, or junctions on
    Windows, and stages them as `<item>.cswap-link-staging`. A planted link in
    the history tree raises instead of being walked. A real (non-link)
    directory is merged under `.cswap-history-migration.lock`, never deleted.
    Losing copies go to `backup_dir/history-conflicts/` (0700).
  - **History sharing is now on by default** (`--no-share-history` or
    `run.shareHistory false` turns it off). Local only.
  - **`switcher.py`:** the `fetch_plan` and header-probe call sites, gated as
    above. Swap and move adopt a rotated credential into the backup through
    the existing writer. `purge` removes legacy `claude-code` items through
    `security`, for cswap's own slot names only.
  - **`cli.py`:** the `menubar` dispatch above. No new subprocess or network
    call.

Swept by the gate only (display and settings): `autoswitch.py`,
`json_output.py`, `models.py`, `settings.py` (the `usage.headerProbe` key was
read), `snapshot_source.py`, `usage_store.py`, `tui/`.

**Published `0.30.0`, `1.0.0` == their tags.** `redflag.sh 0.30.0 --baseline
0.29.0 --repo . --git-ref v0.30.0` and `redflag.sh 1.0.0 --baseline 0.30.0
--repo . --git-ref v1.0.0` both report:

- the PyPI SHA256s verify, and all 45 package files match the tag;
- the wheel and sdist ship identical code;
- stock hatchling, with no hooks;
- only known hosts.

The red flags are the delta lines above, read in full. The 1.0.0 lists of
modules importing network or process machinery are the same as 0.30.0's, and
its new exec-pattern lines are `cli.py`'s `find_spec("rumps")` and
`update_check.py`'s `importlib.metadata`, both read.

| Release | Artifact | SHA256 |
|---|---|---|
| `0.30.0` | wheel | `2966c9de701688f18df007e45e290772c68cdeb63c0f496951969d65231b452a` |
| `0.30.0` | sdist | `6c1b92f0d6e09b82361e56c51b7275afc64de08820fb94964ce04d2bd01a3c27` |
| `1.0.0` | wheel | `19b9d93fdca2fa7792b4d6bd4dfe3be6160d230c3d547fed68c9f15ab707285b` |
| `1.0.0` | sdist | `527721102fc8733ad7228fa4ccc8c7884720970474e14decbaba52e626a977fd` |

**Fork merge `041a626` + `772a72c` (local, not pushed).** It conflicted in
`update_check.py`, `tests/conftest.py` and `tests/test_update_check.py`; the
fork's lines are kept and upstream's added. `772a72c` points the new
`_menubar_extra_missing` remedy at `AUDITED_SOURCE` instead of PyPI. `uv run
pytest -q`: 3554 passed, 12 skipped. A wheel built from `git archive 772a72c`
holds exactly `src/claude_swap/` (46 files, byte-identical), no `.pth`, the
two console scripts, and `Requires-Dist` without `keyring`.

### Also audited: `1.1.0`, and the fork merge `313ec51`

Read on 2026-11-14 by the `downstream` seat while the person was away, and
**adopted on the read**: the role's step 4, since nothing in it is a red flag
(no new host, process, persistence or dependency; the published artifacts
equal the tag). `v1.0.0 → v1.1.0` is 38 upstream commits, 18 files under
`src/`, +1510 / −211; `pyproject.toml` changes only the version.

Read in full, the lines the gate flagged and the code around them:

- **`oauth.py`, network, same host.** A second header probe,
  `_add_scoped_limits`, sends one more 1-token `/v1/messages` request per
  poll to `claude-fable-5-1` on `api.anthropic.com` with the same bearer token
  as the existing Haiku probe, to read Fable's weekly bucket. **Off by
  default**: only with `usage.fableProbe` set (settings.py, `fable_probe:
  bool = False`), and paused while that bucket reads as spent, or when the
  main probe says rejected. Nothing new is sent and no new host is reached;
  with the setting on, each poll spends a token of Fable usage.
- **`paths.py` / `credentials.py`, credential writes.** The active credentials
  file now follows `CLAUDE_SECURESTORAGE_CONFIG_DIR` when it is set, as
  Claude Code does, written atomically through the existing writer. Unset on
  this machine (checked 2026-11-14), so the path is the same as before.
- **`session.py`, environment.** `_default_login_signed_out` pops
  `CLAUDE_CONFIG_DIR` for one local read of the default login and puts it back
  in a `finally`; a non-empty `CLAUDE_SECURESTORAGE_CONFIG_DIR` short-circuits
  it. Used by `cswap run` to launch the session's profile when the default
  login is signed out (#563). No network, no new exec.
- **`claude_locks.py`.** Stale-lock takeover uses `lstat` and `unlink`s a file
  or symlink planted at the takeover path instead of following it; sleeps are
  clamped to the remaining budget; a failing keep-alive touch warns instead
  of letting the lock go silently stale. Tightens.
- **`switcher.py`.** `_rescue_foreign_successor` (#489, #523) writes the live
  credential into the slot it belongs to, only when its `expiresAt` is
  strictly newer than that slot's stored backup and it holds a full token
  pair, after the safety copy is written; it writes nothing into the current
  slot. A switch with `CLAUDE_CONFIG_DIR=~/.claude` no longer deletes the
  login made without the variable (#582); usage polling from another profile
  no longer refreshes the default login (#433); backups survive incompatible
  live stores (#384). Local only, into the user's own slots.
- **macOS only, adopted on the read:** another profile's Keychain item is no
  longer written (#357); menu bar display.

Swept by the gate only (display, settings and docs): `autoswitch.py` (room
ranking for auto-switch targets), `cli.py`, `json_output.py`, `lines.py`,
`locking.py`, `models.py`, `poll_policy.py`, `settings.py` (an unread key is
named), `tui/`. No added line spawns a process.

**Published `1.1.0` == its tag.** `redflag.sh 1.1.0 --baseline 1.0.0 --repo .
--git-ref v1.1.0`: the PyPI SHA256s verify, all 45 package files match the
tag, the wheel and sdist ship identical code, only known hosts. Its one red
flag is the 10 delta lines above, read; runtime dependencies are unchanged.

| Release | Artifact | SHA256 |
|---|---|---|
| `1.1.0` | wheel | `3fb3267272a8396b3d24ae04882a3d858a69fe7f2763a9d4d4716b92595bc355` |
| `1.1.0` | sdist | `54ce53b4f15519f8b3c0b0cba75c5ed680270ccd3b25da931bbc30b3d5146a67` |

**Fork merge `313ec51`** (`git merge --no-ff v1.1.0`). It conflicted in
`.gitignore` only, both entries kept. `pyproject.toml` and `uv.lock` equal
the tag's, and the fork's own `src/` patch on top of upstream is line for
line the one `41cc1fb` carried. `uv run pytest -q`: 3826 passed, 12 skipped.
A wheel built from `git archive 313ec51` with `uv build` holds exactly
`src/claude_swap/` (46 files, byte-identical), no `.pth`, the two console
scripts, and `Requires-Dist` `textual`, `truststore` and `rumps` (the
`menubar` extra) only.

### Also audited: fork PR #1 (Codex account switching), the merge `5477d73` and `5e5bc7d`

Read on 2026-11-21 by the `downstream` seat, on the person's word ("chck and
merge", in this seat's chat, relayed to desk #373 as option 1). Not an
upstream release: the fork's own branch `feature/codex-port` (`cffde41`,
`6a40610`, `c109717`), a port of Codex support from the MIT-licensed
`errhythm/ccswap` at `e7f2513`, same copyright holder. 54 files, +18858 / −70;
about 9,800 lines under `src/`, 9 new modules.

**New network hosts, approved by the person** (the red flag that sent it to
them): `chatgpt.com/backend-api` (`/wham/usage`, `/wham/rate-limit-reset-credits`,
and `.../consume` only after a y/N prompt or `--yes`) and
`auth.openai.com/oauth/token` (refresh grant, Codex's public client id
`app_EMoamEEZ73f0CkXaXp7hrann`, URL hard-coded). `api.openai.com/auth`,
`/profile` and `chat.openai.com` appear only as JWT claim names, never
requested. Every call is `urllib` in `codex_usage.py`; no other new module
touches the network. No other new host in `src/` (grep of every URL against
`f5b8237`).

Read in full, every line, by two Opus readers splitting the source (core:
`codex.py`, `codex_usage.py`, `codex_usage_store.py`, `codex_autoswitch.py`,
`reset_credit_display.py` and the diffs of `cli.py`, `usage_server.py`,
`paths.py`, `json_output.py`, `settings.py`, `poll_policy.py`, `oauth.py`,
`appearance.py`, `switcher.py`, `tui/dashboard.py`; process: `codex_session.py`,
`codex_binary.py`, `process_detection.py`, `windows_job.py`,
`tui/codex_watch.py` and the diffs of `menubar.py`, `launch_agent.py`). No red
flag. What they found:

- **Credentials.** `~/.codex/auth.json` and the saved slots
  (`<XDG data>/claude-swap/codex/credentials/account-N.json`) are written
  through mkstemp + fchmod 0600 + fsync + `os.replace`, directories 0700; an
  unmanaged live login is refused, not overwritten, and the live one is saved
  to its slot before a swap. Parse errors re-raise `from None` with fixed
  text; no token reaches stdout, JSON output, logs or the usage socket (its
  `codex` section: slot, kind, windows, credits, an error class name).
- **Processes.** `pgrep -x codex`; `codex run` launches the `codex` found on
  PATH with `shell=False`, its option parser refusing login- and
  routing-changing `-c` keys; the version probe runs with a credential-free
  environment in a temp home. Signals go only to children cswap started;
  `prctl(PR_SET_CHILD_SUBREAPER)` on itself. ctypes: `renameat2` with
  `RENAME_NOREPLACE`. The Linux `/proc` scan reads `environ` of the user's own
  processes and keeps only `CODEX_HOME`.
- **Persistence.** None on Linux. macOS: the LaunchAgent plist carries
  `CODEX_HOME`; Codex auto-switch in the menu bar is off by default.
- **Destructive.** `rmtree`/`unlink` confined to the session homes under the
  backup root, after ownership and link checks; a slot is deleted only after a
  prompt; `cswap purge` now also removes `codex/` (warned).
- **Accepted concerns.** (1) `chatgpt_base_url` in `$CODEX_HOME/config.toml`
  redirects the usage calls and their bearer tokens, as it redirects Codex
  itself; unset here. (2) A 30x from the backend would carry `Authorization`
  to the redirect target (urllib's default), the same plain `urlopen` the
  audited Anthropic code uses. (3) Windows only: `shutil.which` searches the
  current directory first. (4) Session homes symlink the shared Codex config,
  prompts and skills, by design; never `auth.json`.

**Two fixes before the merge.** `c109717` (the branch's author, after this
seat's review): the Codex setup made the data directory before
`migrate_legacy_backup_dir` ran, so a later migration would refuse, or on an
interrupted one `rmtree` the stored Codex logins; it now migrates first,
under a lock, and refuses a destination holding `codex/`. `5e5bc7d` (this seat):
on this machine's kernel a zombie's `/proc/PID/environ` answers ESRCH, not
empty, so any zombie left every Codex scan "uncertain" and blocked switching
(two leftover `codex` zombies here); the real-`/proc` smoke test failed on it.

**Checked.** `nice -n 19 uv run pytest -q` on `5e5bc7d`: 5825 passed, 18 skipped.
`pyproject.toml` and `uv.lock` unchanged since `f5b8237`, so the runtime
dependencies are too. A wheel built with `uv build --wheel` holds exactly
`src/claude_swap/`, every file byte-identical to the tree, no `.pth`, the two
console scripts.

**Follow-up `348c385`** (this seat, on the person's word, 2026-11-21: no Codex
add button in the TUI). The Codex screen binds `a` (save the current login)
and `x` (remove the selected slot), each behind a `ConfirmModal`, calling the
same `add_account()` / `remove_account(n, assume_yes=True)` the CLI runs,
through `tui.data.run_action` (stdout captured, stdin empty). The dashboard's
Add menu opens that screen on the add confirmation. TUI only: no new call,
host, file or process. Tests: 5826 passed, 18 skipped.

**Follow-up `71282f6`** (this seat, on the person's word, 2026-11-21: Codex
quotas on the watch pane as Claude's, under their own header). The watch
screen adds a Codex section of the same cards, read every interval in a
thread worker through `CodexAccountSwitcher(initialize_storage=False)
.accounts_snapshot()`, the call `cswap codex watch` already makes (its usage
fetch goes to the approved `chatgpt.com` host); `usage_rows` draws Codex's
`weekly` window as the 7d row. `7474b28` changes a test only: the real-`/proc`
smoke test is judged by its own child, since parallel workers' children made
it flaky. Tests: 5828 passed, 18 skipped, six runs in a row.

### Also audited: `1.2.0`, and the fork merge `6aa982f`

Read on 2026-11-26 by the `downstream` seat while the person was away, and
**adopted on the read** (the role's step 4: no new host, process, persistence
or dependency; the published artifacts equal the tag). `v1.1.0 → v1.2.0` is 15
upstream commits, 12 files under `src/`, +463 / −70; `pyproject.toml` changes
only the version.

Read in full, the lines the gate flagged and the code around them:

- **`oauth.py`, network, same host.** The refresh request is unchanged. What
  changed is how a failed refresh is classified and logged:
  - The error reply's body is no longer written to the debug log. Only the
    HTTP status and a known RFC 6749 error code go in.
  - A failure before anything was sent (name lookup, connection refused, a
    certificate rejected) is logged quietly.
  - A timeout, a reset or a 5xx after the request may have gone out is
    logged at WARNING, with the first 19 characters of the credential's
    existing SHA-256 fingerprint and a hint to re-add the account.

  `import socket` serves only the `socket.gaierror` type in that
  classification. No token or reply text reaches a log; this tightens what
  is logged.
- **`switcher.py` / `session.py` / `autoswitch.py`, credential refresh.**
  - A backup refresh whose grant the live login also holds is no longer
    sent (`live-login`). The check compares the fingerprints of the live
    store and the slot's credential. Claude Code renews that grant, which
    avoids two holders spending one refresh token.
  - `cswap run` refuses to seed a session profile with the live login's
    grant.
  - Each refresh request is bracketed in the log at INFO: a start line, then
    how it ended, by fingerprint head.

  Local only; no new call.
- **`cli.py`.** `cswap run` sends its own notices to stderr
  (`contextlib.redirect_stdout`), so stdout carries only claude's output.
  `_person_at_terminal` sets the switcher's `interactive` flag from
  `isatty()`; it is read only by the macOS Keychain migration.
- **macOS only, adopted on the read:** the Keychain migration waits for the
  permission window when a person runs the command
  (`migrations.py`, `macos_keychain.py`, `KeychainTimeout`).

Swept by the gate only (display and settings): `ui.orgTag` (`auto`/`on`/`off`)
in `settings.py`, `models.py`, `switcher.py` listings and `tui/`. No added
line spawns a process.

**Published `1.2.0` == its tag.** `redflag.sh 1.2.0 --baseline 1.1.0 --repo .
--git-ref v1.2.0`: the PyPI SHA256s verify, all 45 package files match the
tag, the wheel and sdist ship identical code, only known hosts. Its one red
flag is the 3 delta lines in `oauth.py` above, read; runtime dependencies are
unchanged.

| Release | Artifact | SHA256 |
|---|---|---|
| `1.2.0` | wheel | `f5a7aa4c7ecced029850556ea5484dbc1c04e346814c555b10776c257e659f00` |
| `1.2.0` | sdist | `e338e2d3a715a58cca86a1c3f571854ee0f946e8dc1dc4b292e72afb406ccaf1` |

**Fork merge `6aa982f`** (`git merge --no-ff v1.2.0`). It conflicted in three
places, each resolved by keeping both sides:
- `cli.py`: the fork's Codex list branch, then upstream's `interactive=`
  constructor;
- `switcher.py`: `__init__` takes upstream's `interactive` and the fork's
  keyword-only `initialize_storage`;
- `tests/test_config_cli.py`: the settings count is 17 (the fork's two
  weekly thresholds plus upstream's `ui.orgTag`).

The fork's own `src/` patch on top of upstream is line for line the one
`7474b28` carried, but for that `__init__` signature. `pyproject.toml` and
`uv.lock` equal the tag's. `uv run pytest -q`: 5895 passed, 18 skipped. A
wheel built from `git archive 6aa982f` with `uv build` holds exactly
`src/claude_swap/` (55 files, byte-identical), no `.pth`, the two console
scripts, and `Requires-Dist` `textual`, `truststore` and `rumps` (the
`menubar` extra) only.

### To run exactly the audited version

```bash
uv tool install 'claude-swap==1.2.0'       # current stable — verified clean
# or the audited fork commit (pin the full sha; a branch name moves):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@6aa982f0f06751862d8ef3416ebe682adce8220c'
# or follow the fork's audited tag (what `cswap upgrade` runs):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@audited'
```

Any commit after `6aa982f` that touches `src/` or `pyproject.toml` is
**unaudited**. The `audited` tag points at the commit that records this
sentence. Its code is `6aa982f`'s: the commits after it touch only this file
and `docs/`.

**Marker history** (the old commit is recorded here before each move, as the
seat's grant requires):

| Date | `audited` moved from | to | Code audited |
|---|---|---|---|
| 2026-10-16 | (new) | `d138f8d` | `70dde18` |
| 2026-10-16 | `d138f8d` | `a2b2f43` | `59d9ffb` |
| 2026-11-04 | `a2b2f43` | `57d54c1` | `babc945` |
| 2026-11-09 | `57d54c1` | `4f6b2bd` | `41cc1fb` |
| 2026-11-14 | `4f6b2bd` | `f5b8237` | `313ec51` |
| 2026-11-21 | `f5b8237` | `77facd7` | `5e5bc7d` |
| 2026-11-21 | `77facd7` | `d73a8ef` | `348c385` |
| 2026-11-21 | `d73a8ef` | `f2d5228` | `7474b28` |
| 2026-11-26 | `f2d5228` | the commit adding this row | `6aa982f` |

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
| 2026-10-25 | v0.1.88 → v0.1.91 (hard; desk #110 now asks for v0.1.91, pin stays) | 3 hard: `persistence` in skills/repo-rename/SKILL.md:42 (as before; host-move's `crontab` line is gone in the rewrite), and two `pipe to shell` lines, skills/host-move/SKILL.md:124 and bin/onboard.py:807; read: credential lines in the new skills/onboard/ADOPT.md and as before; network lines in watchdog.py, onboard.py:806, ADOPT.md, host-move | The v0.1.88 → v0.1.90 reads above, then the whole v0.1.90 → v0.1.91 diff outside docs/ and tests/: watchdog.py, drivers/zulip/plugin.py, bin/onboard.py, .githooks/pre-commit.d/10-abs-paths, classes/desk/export.py, priority.py, queue.py; ADOPT.md's rules and survey; the skills' prose and their `disable-model-invocation` | Safe here. The pipe-to-shell lines are printed for the person, never run: `--preflight` hands them a terminal line that fetches the bootstrap from their own private desk, pinned to a commit sha, and pipes it to `sh`. The new `hooked()` refuses a punch-in from a session without the plugin's hooks; this session passes (BLUEPRINTS_KIT set, `loaded-<pid>` on the rack), so a move's restart still works. onboard.py deletes a seat's merged drafts from the desk, run by the person. ADOPT.md, a prototype the person starts, says never to read a key file. 10-abs-paths may allow a repo's own top-level folders (`[repo] host_paths`, not set here). The desk orders unranked projects last. No new host; nothing reads the logins. |
| 2026-10-25 | v0.1.88 → v0.1.92 (hard; desk #110 now asks for v0.1.92, pin stays) | 3 hard, the same lines as v0.1.91: `persistence` in skills/repo-rename/SKILL.md:42, `pipe to shell` in skills/host-move/SKILL.md:124 and bin/onboard.py:807 | The v0.1.88 → v0.1.91 reads above, then the whole v0.1.91 → v0.1.92 diff outside docs/ and tests/: watchdog.py (`pinned_version`, `reload_crutch`, the prompt hook's call to it, `prune_gone`), the new drivers/herdr/reload.py, .githooks/pre-commit.d/10-abs-paths, classes/builder/BUILDER.md, CLAUDE.md | Safe here. New: when a held seat's session runs an older kit than installed_plugins.json records for this clone, the prompt hook starts reload.py detached (at most 3 per pinned version), which asks the terminal multiplexer (`herdr`, or `$HERDR_BIN_PATH`) about the session's own pane (`$HERDR_PANE_ID`, set in this session) and types the fixed text `/reload-plugins` and Enter only when that pane still runs the same session, is idle, unfocused and its input line empty; it sends Enter only if the line then reads exactly that text. Local only: no network, no other text, nothing reads the logins. It runs only from v0.1.92's own hooks, so it helps the moves after this one. 10-abs-paths judges a whole path, not its tail. No new host. |
| 2026-10-25 | v0.1.88 → v0.1.93 (hard; desk #110 now asks for v0.1.93, pin stays) | 3 hard, the same lines as v0.1.91 and v0.1.92 | The v0.1.88 → v0.1.92 reads above, then the whole v0.1.92 → v0.1.93 diff outside docs/ and tests/: hooks/forge-gate.sh, forge_gate.py, watchdog.py (`seat_plugins`, the `brief` watcher), the new drivers/git/watch-brief.sh, watch-remote.sh, bin/report-to-kit.py (`--behavior`), BASE.md, rules/RETRO.md, UNATTENDED.md, the new skills/change-priming, the host-move and report-to-kit skills, BUILDER.md, REVISER.md | Safe here, with one setting. The forge gate now checks only sessions that hold a seat (#162), so an unseated session here (the person's own, a helper) would post to GitHub unchecked; `[repo] forge_gate_unseated = true`, set in .blueprints.toml in the same commit as this row, keeps every session gated (a key v0.1.88 does not read: it gates every session already). The `brief` watcher, which every seat now runs, polls this repo's own remote for commits to the seat's priming; no new host. report-to-kit's `--behavior` lists and comments on the kit's issues through `gh`, after the same leak check. BASE.md now lets anyone change a seat's brief by the `change-priming` skill, the seat told and reading it as its adversary. Nothing reads the logins. |
| 2026-10-25 | v0.1.88 → v0.1.94 (hard; desk #110 now asks for v0.1.94, pin stays) | 3 hard, the same lines as v0.1.91 to v0.1.93 | The v0.1.88 → v0.1.93 reads above, then the whole v0.1.93 → v0.1.94 diff outside docs/ and tests/: watchdog.py (`nothing`, `base_unseated`, the base at punch-in), ledger.py, nightly.py (the `label` job), watch-issues.py (a seat's own `Seat:` posts left out), watch-brief.sh, the new drivers/leaves/leaves.py and relay.sh (chain.py gone), openrouter-leaf.py, agents/consensus.md and trunk-review.md, the leaf, three-leaf, four-leaf and consensus skills, rules/WAKE_LABELS.md, scripts/wake-corpus.py, BASE.md | Safe here. The outside-model runs now go through relay.sh, which runs a relay script with node from the clone that `~/.config/agent-seat-blueprints/relays` names (on this machine, a clone of the person's delegation skills), only when it stands at the commit pinned in relay.sh. None of it runs here: consensus step 1 still reads `[repo] outside = "never"` (repo-prep), and TRUST.md keeps those agents off this repo. The nightly `label` job, run by one seat per machine that names it (none here), reads every seat's transcripts on this machine, this one's included, and labels each wake with small Claude subagents into a 0600 file; nothing leaves the machine. `watchdog.py nothing` records a ledger verdict. `[repo] base_unseated` defaults to true, so nothing changes here. No new host; nothing reads the logins. |
| 2026-10-26 | v0.1.88 → v0.1.95 (hard; desk #110 now asks for v0.1.95, pin stays) | 4 hard: `persistence` in skills/repo-rename/SKILL.md:42, `pipe to shell` in skills/host-move/SKILL.md:124 and bin/onboard.py:895 (the line that was :807), and a new one, bin/onboard.py:903, the overlay variant of the same printed bootstrap line | The v0.1.88 → v0.1.94 reads above, then the v0.1.94 → v0.1.95 diff outside docs/ and tests/ (67 files): whole for hooks/hooks.json, forge-gate.sh, forge_gate.py, .githooks/pre-push, bootstrap.sh.in, move-to-tag.py, outbound-copy.sh, relay.sh, openrouter-leaf.py, drivers/zulip/plugin.py, desk/post.py, hand.sh, herdr/reload.py, rules/TRUST.md, digest.py; watchdog.py's additions; bin/overlay.py, sync-shared.sh, agents/process-analyst.md and wake-classes.md scanned for network calls and removals | Safe here; most of it tightens. onboard.py:903 is printed for the person (fetch the bootstrap from their private desk at a commit sha, `sh -s SEATS --overlay`), never run. The forge gate now follows `gh` inside `$(...)` and `sh -c`, and counts a session as seated only by a seat card (#177); this repo gates every session anyway (`forge_gate_unseated`). A new `StopFailure` hook runs the same watchdog hook. relay.sh refuses a relays clone with local changes or a relay file not in its pinned commit. The Zulip plugin answers a forwarded message only from the seat's own sibling account, and asks Zulip whether an account is online. The trust rule left BASE.md for rules/TRUST.md, which the digest names in every session here (docs/TRUST.md exists). The digest counts how far each READ_TO mark is behind. overlay.py and sync-shared.sh are for overlay repos and shared checkouts; neither is used here. The two new agents run only when called; process-analyst is on Opus and wake-classes on Sonnet, and neither calls an outside model. No new host; nothing reads the logins. |
| 2026-10-27 | v0.1.88 → v0.1.96 (hard; desk #110 now asks for v0.1.96, pin stays) | the same 4 hard lines as v0.1.95: `persistence` in skills/repo-rename/SKILL.md:42, `pipe to shell` in skills/host-move/SKILL.md:124 and bin/onboard.py:913 and :921 (the lines that were :895 and :903, unchanged) | The v0.1.88 → v0.1.95 reads above, then the v0.1.95 → v0.1.96 diff outside docs/ and tests/ (28 files): whole for forge_gate.py, leak-gate.sh, onboard.py, drivers/zulip/plugin.py, rules/AUTOMODE.md, .blueprints.toml; watchdog.py's code lines; drivers/github/watch-issues.py scanned for network calls; agents/competitor-survey.md read | Safe here. The forge gate now also denies a bare `gh issue close` on the desk, and after a write it lets through from a seated session it appends a 16-hex sha256 digest of the body (and `close:N:<epoch>`) to a local file under $XDG_STATE_HOME, so the issues watcher does not echo the seat's own comment; digests only, nothing sent. The watchdog now runs the v0.1.92 reloader itself every 60 s, which acts only when the pin is ahead of the running copy (the tracker moves the pin here), and reacts to announcements of a release the session already runs. The quota lines now say transitions only. An announcement no longer wakes a seat other than tooling where the table declares a tooling seat; this repo declares none, so downstream still wakes. leak-gate's status reads a core.hooksPath gate as on. onboard.py arms a revised first-seating handout once. watch-issues.py fetches claim tags from its own origin (the kit's tooling seat; not configured here). competitor-survey is a new Opus contractor with WebSearch and WebFetch that reads a caller's repo; it runs only when called and is not called here. No new host; nothing reads the logins. |
| 2026-10-27 | v0.1.88 → v0.1.97 (hard; desk #110 now asks for v0.1.97, pin stays) | the same 4 hard lines as v0.1.96 (repo-rename:42, host-move:124, onboard.py:913 and :921) | The v0.1.88 → v0.1.96 reads above, then the whole v0.1.96 → v0.1.97 diff outside docs/ and tests/ (5 files, 34 lines) | Safe here. post.py reads the desk clone's `remote.origin.url` and `origin/HEAD` with local git and passes that branch to `gh workflow run --ref` (#197), so a token without Contents read can start the desk's post workflow; nothing new is sent. BASE.md and the admin and lead texts only say the watchdog reacts to a release announcement for the seat. No new host; nothing reads the logins. |
| 2026-10-27 | v0.1.88 → v0.1.98 (hard; desk #110 now asks for v0.1.98, pin stays) | the same 4 hard lines as v0.1.97 (repo-rename:42, host-move:124, onboard.py:913 and :921) | The v0.1.88 → v0.1.97 reads above, then the v0.1.97 → v0.1.98 diff outside docs/ and tests/ (20 files): the code lines of watchdog.py, forge_gate.py, automode.py, land.sh, desk/post.py, forge.py, watch-answers.py, watch-issues.py | Safe here. The watchdog's reloader now reads the session's own loaded version from its rack record instead of the watchdog's copy (#200), and a person's direct message or mention on Zulip marks the seat present again (local marks only). automode.py's check names the allow-entry items a machine lacks. The forge gate says why when the working directory was removed; land.sh prints where to cd. The desk scripts accept `**Update:**`, `**Your move:**` and `**Done:**` lines, allow an answer on a withdrawn question already closed, and say an answer taken back. No new host; nothing reads the logins. |
| 2026-10-31 | v0.1.88 → v0.1.99 (hard; desk #110 now asks for v0.1.99, pin stays) | the same 4 hard lines as v0.1.98 (repo-rename:42, host-move:124, onboard.py:913 and :921) | The v0.1.88 → v0.1.98 reads above, then the v0.1.98 → v0.1.99 diff outside docs/ and tests/ (19 files): hooks.json, plugin.json, the kit's own .blueprints.toml, watchdog.py, the zulip and watch drivers, overlay.py, the new bin/seats-export.py and mods/seats/register.tsx | Safe here. hooks.json now loads one UI module, mods/seats/register.tsx (a status line, a band while the quota hold is on, a `/seats-view` pane): it reads XDG_RUNTIME_DIR and the local seat rack, no network. bin/seats-export.py writes this machine's seats (held or not, watcher states, quota reading, wake counts, commit counts by Seat line, roadmap and inbox item titles) to the person's own desk repo as seats/<site>.json, at most daily, through `gh api` contents PUT; it runs only as a watcher of the kit's own lead seat, never from this repo's table, and this repo has no docs/ROADMAP.md or inbox files for it to read. The watchdog wakes a seat when five or more seats' messages wait unshown, says a quota hold's end, and rewrites a channel mention to the online instance (the same Zulip server). overlay.py refuses instead of guessing when XDG_RUNTIME_DIR or the [repo] id is missing. The kit's table names a prime seat (its lead), which may clear another seat's stuck local state. No new host; nothing reads the logins. |
| 2026-10-31 | v0.1.88 → v0.1.100 (hard; desk #110 now asks for v0.1.100, pin stays) | the same 4 hard lines as v0.1.99 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.99 reads above, then the v0.1.99 → v0.1.100 diff outside docs/ and tests/ (10 files): rules/AUTOMODE.md, watchdog.py, drivers/herdr/reload.py, drivers/leaves/leaves.py, agents/consensus.md, mods/seats/register.tsx | Safe here. The auto-mode allow entry gains item (9): a read-only search (`git grep`, `grep`, `rg`, `git log -S/-G`, piped into `cut`, `head` or `wc` at most) or a document may name a destructive command, and the command itself is still judged on its own; it takes effect only when the person pastes the entry again. The pane reloader also starts at a turn's end and, where the herdr plugin `claude-reload` is enabled, hands off to it through a request file in that plugin's config folder (local only). The consensus engine may run a `claude` leaf on sonnet, haiku or fable; this repo runs no consensus agents (TRUST.md, `outside = "never"`). The seats pane only changed its layout. No new host; nothing reads the logins. |
| 2026-10-31 | v0.1.88 → v0.1.101 (hard; desk #110 now asks for v0.1.101, pin stays) | the same 4 hard lines as v0.1.100 (repo-rename:42, host-move:124, onboard.py:913 and :921); three new `network` READ lines, all in the orphan wake below | The v0.1.88 → v0.1.100 reads above, then the v0.1.100 → v0.1.101 diff outside docs/ and tests/ (3 files): watchdog.py, BUILDER.md, plugin.json | Safe here. Every 60 s a seat's watchdog looks at the sibling seats' cards on this machine; when one's watchdog is dead under a live session, it posts one fixed wake-up line to that session's own local socket, once per dead watchdog (an exclusive mark file), and that session's prompt hook starts a new watchdog. SIGTERM and SIGHUP are now logged before stopping. Local sockets and files only. No new host; nothing reads the logins. |
| 2026-10-31 | v0.1.88 → v0.1.102 (hard; desk #110 now asks for v0.1.102, pin stays) | the same 4 hard lines as v0.1.101 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.101 reads above, then the v0.1.101 → v0.1.102 diff outside docs/ and tests/ (10 files): watchdog.py, claim.sh, seats-export.py, desk/export.py, desk/forge.py, drivers/github/issues.py, plan-watch.py | Safe here. The watchdog is now started through a launcher that exits at once, so a plugin reload no longer kills it, and one stopped by a signal keeps its card. The desk's reader (forge.py) knows the `update` and `closed` event lines, whose absence crashed the desk's queue, mover and export on a comment holding only `**Update:**` (as #110's later comments do). desk/export.py adds stamps, relayed context and order history from the desk's own issues and git log; the forge query adds the issue's thumbs-up reactions. claim.sh takes `-s REPO/SEAT`. No new host; nothing reads the logins. |
| 2026-10-31 | v0.1.88 → v0.1.103 (hard; desk #110 now asks for v0.1.103, pin stays) | the same 4 hard lines as v0.1.102 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.102 reads above, then the v0.1.102 → v0.1.103 diff outside docs/ and tests/ (4 files): desk/post.py, desk/export.py, rules/AUTOMODE.md | Safe here. post.py takes `--relayed note`, which adds a hidden `<!-- relayed:note -->` line to a desk comment, and the desk export counts such a comment as context the person gave. The auto-mode allow entry's item (8) names that flag (2026-10-31, revision 2); it takes effect only when the person pastes the entry again. No new host; nothing reads the logins. |
| 2026-11-01 | v0.1.88 → v0.1.104 (hard; desk #110 now asks for v0.1.104, pin stays) | the same 4 hard lines as v0.1.103 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.103 reads above, then the v0.1.103 → v0.1.104 diff outside docs/ and tests/ (12 files, all but plugin.json and two texts in classes/desk/) | Safe here. Desk scripts only: the A/B trial runs as a chain of pairs (trial.py), the queue and export read an answer after a withdrawal as its outcome, and the desk watcher calls an answer on a question closed over 7 days ago history. No added subprocess, forge or network call; this seat runs none of them but post.py, which is unchanged. No new host; nothing reads the logins. |
| 2026-11-01 | v0.1.88 → v0.1.105 (hard; desk #110 now asks for v0.1.105, pin stays) | the same 4 hard lines as v0.1.104 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.104 reads above, then the v0.1.104 → v0.1.105 diff outside docs/ and tests/ (10 files): watchdog.py, claim.sh, desk/export.py, desk/watch-answers.py, the kit's own .blueprints.toml | Safe here. A stop asked for stays a stop when a SIGTERM or SIGHUP follows it (#216); claim.sh refuses an empty seat; the desk watcher reads a file desk's close time from its Closed line; the desk export's orders say unknown on an unreadable order.toml; the kit's lead now wakes the kit's tooling seat. No added subprocess, forge or network call. No new host; nothing reads the logins. |
| 2026-11-02 | v0.1.88 → v0.1.106 (hard; desk #110 now asks for v0.1.106, pin stays) | the same 4 hard lines as v0.1.105 (repo-rename:42, host-move:124, onboard.py:913 and :921); two new files listed, bin/watchdog.sh and bin/wt.sh | The v0.1.88 → v0.1.105 reads above, then the v0.1.105 → v0.1.106 diff outside docs/ and tests/ (9 files): move-to-tag.py, watchdog.sh, wt.sh, plan-state.sh, watchdog.py, quota.py | Safe here. bin/watchdog.sh runs watchdog.py from the plugin-cache copy the clone pins (found by `move-to-tag.py --copy`, which now refuses when the pinned version is not in the cache); bin/wt.sh fetches origin and adds a worktree under `.worktrees/` in the clone it is run in; `quota.py --line` prints the quota reading as one line. An important message from a seat is shown again until acknowledged (D152). No new host; nothing reads the logins. |
| 2026-11-02 | v0.1.88 → v0.1.107 (hard; desk #110 now asks for v0.1.107, pin stays) | the same 4 hard lines as v0.1.106 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.106 reads above, then the v0.1.106 → v0.1.107 diff outside docs/ and tests/ (6 files): watchdog.py, drivers/claude-code/transcripts.py, .gitignore | Safe here. transcripts.py's `--project` also takes a project folder's own path, accepted only when it sits directly under the projects root, so it reads no folder it read no way before; it still only reads, locally. A notice is marked important only by a marker right after its opener (#218). No new host; nothing reads the logins. |
| 2026-11-02 | v0.1.88 → v0.1.108 (hard; desk #110 now asks for v0.1.108, pin stays) | the same 4 hard lines as v0.1.107 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.107 reads above, then the v0.1.107 → v0.1.108 diff outside docs/ and tests/ (11 files): watchdog.py, wt.sh, seats-export.py, drivers/herdr/reload.py, mods/seats/register.tsx, rules/AUTOMODE.md | Safe here. A watchdog sent SIGTERM or SIGHUP keeps its card when it cannot tell whether its session lives (#222); wt.sh asks origin for its default branch; seats-export.py adds per-seat wake totals (counts only) to the document it already writes to the person's desk; the seats pane shows them. The auto-mode allow entry's item (2) extends to the kit's lead seats commenting on and closing kit issues (dated 2026-11-02); it takes effect only when the person pastes the entry again, and this seat files no kit issues it would cover. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.109 (hard; desk #110 now asks for v0.1.109, pin stays) | the same 4 hard lines as v0.1.108 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.108 reads above, then the v0.1.108 → v0.1.109 diff outside docs/ and tests/ (3 files): desk/watch-answers.py, EDGES.md, plugin.json | Safe here. One line in the desk's answer watcher: an HTTP 500 or an empty or cut answer from the forge counts as a passing failure. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.110 (hard; desk #110 now asks for v0.1.110, pin stays) | the same 4 hard lines as v0.1.109 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.109 reads above, then the v0.1.109 → v0.1.110 diff outside docs/ and tests/ (2 files): desk/watch-answers.py, plugin.json | Safe here. One pattern in the desk's answer watcher: a forge reply that is not JSON (an edge's HTML page) also counts as a passing failure (#224). No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.111 (hard; desk #110 now asks for v0.1.111, pin stays) | the same 4 hard lines as v0.1.110 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.110 reads above, then the v0.1.110 → v0.1.111 diff outside docs/ and tests/ (5 files): mods/seats/register.tsx, desk/watch-answers.py | Safe here. The seats pane leaves out the wakes section for an export that predates its per-seat totals (#225); the desk watcher's header text names the link failures it waits out. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.112 (hard; desk #110 now asks for v0.1.112, pin stays) | the same 4 hard lines as v0.1.111 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.111 reads above, then the v0.1.111 → v0.1.112 diff outside docs/ and tests/ (3 files): drivers/git/watch-remote.sh, CLAUDE.md, plugin.json | Safe here. watch-remote.sh takes `--removes ERE` with `--path`: only commits whose diff over those paths deletes a matching line are said. The ERE is quoted into `grep -E -e` and checked first, so it is never run as shell; it reads the local clone's git history only. This repo's watchers do not use it. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.113 (hard; desk #110 now asks for v0.1.113, pin stays) | the same 4 hard lines as v0.1.112 (repo-rename:42, host-move:124, onboard.py:913 and :921); the other findings only moved lines | The v0.1.88 → v0.1.112 reads above, then the v0.1.112 → v0.1.113 diff outside docs/ and tests/ (8 files): watchdog.py, mods/seats/register.tsx, drivers/herdr/reload.py, the kit's own .blueprints.toml | Safe here. The UI module now starts one process at each session start and each `/reload-plugins`: `watchdog.py loaded $PPID` from the plugin's own root, which writes the file `loaded-<PID>` naming the kit copy on the local rack. It refuses a PID that is not its own ancestor (read from /proc). reload.py's text says how to link the herdr plugin; it installs nothing. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.114 (hard; desk #110 now asks for v0.1.114, pin stays) | the same 4 hard lines as v0.1.113 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.113 reads above, then the v0.1.113 → v0.1.114 diff outside docs/ and tests/ (3 files): BASE.md, desk/watch-answers.py, plugin.json | Safe here. BASE.md: an answer the person gives in chat to a desk question is relayed to the desk first, and a seat turning unattended files, relays or withdraws its chat questions. The desk's answer watcher skips an answer the watching seat relayed itself (#228). No added subprocess, forge or network call. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.115 (hard; desk #110 now asks for v0.1.115, pin stays) | the same 4 hard lines as v0.1.114 (repo-rename:42, host-move:124, onboard.py:913 and :921); one new READ `credential` line, rules/AUTOMODE.md:95 (the admin rule's text naming the Zulip organisation's accounts, prose) | The v0.1.88 → v0.1.114 reads above, then the v0.1.114 → v0.1.115 diff outside docs/ and tests/ (6 files): hooks/hooks.json, watchdog.py, bin/automode.py, rules/AUTOMODE.md | Safe here. hooks.json only adds a timeout to each existing hook (150 s for the watchdog's, 60 s for the base and forge gate); the commands are unchanged. The prompt hook starts `watchdog.py restart SEAT` detached (the kit's own script, no network of its own) instead of restarting inside the hook. The auto-mode allow rules are split into one entry per rule, `Agent seats kit, rule N`: compared word by word with v0.1.114's items (1) to (9), each rule's text is unchanged, so nothing widens; automode.py still writes no settings file and prints only what the person's settings lack. After a move the person pastes every rule and the environment entry once and removes the old single allow entry. No new host; nothing reads the logins. |
| 2026-11-03 | v0.1.88 → v0.1.116 (hard; desk #110 now asks for v0.1.116, pin stays) | the same 4 hard lines as v0.1.115 (repo-rename:42, host-move:124, onboard.py:913 and :921); no other finding changed | The v0.1.88 → v0.1.115 reads above, then the v0.1.115 → v0.1.116 diff outside docs/ and tests/ (7 files): hooks/hooks.json, hooks/forge-gate.sh, drivers/claude-code/transcripts.py, rules/RETRO.md | Safe here, and stricter. The forge gate's hook drops `|| true` and sets `"onFailure": "block"` (#234): a gate past its 60 s timeout, or whose script is gone, now denies the shell call instead of letting it through. The cost: with the plugin copy removed under a running session, every Bash call of that session is blocked until `/reload-plugins`. transcripts.py gains `hooks`, a local count of hooks the client ended or that failed, read from transcripts; no writes, no network. No new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.117 (hard; desk #110 now asks for v0.1.117, pin stays) | 5 hard lines: the same 4 as v0.1.116, the onboard.py two now at :979 and :987 (repo-rename:42, host-move:124), plus rules/AUTOMODE.md:143, the text of the new auto-mode rule 10, which quotes the bootstrap pipe (`gh api .../seating/bootstrap.sh?ref=<commit> | sh -s <seats>`); no other finding changed | The v0.1.88 → v0.1.116 reads above, then the v0.1.116 → v0.1.117 diff outside docs/ and tests/ (8 files): bin/onboard.py, drivers/zulip/join.py, rules/AUTOMODE.md, the builder, liaison and pm role texts, the kit's own .blueprints.toml | Safe here; nothing new runs by itself. onboard.py asks the forge (`gh api repos/<slug>`, a read) what a renamed repository is called now and prints, never runs, the `git remote set-url` line for the person; it names untracked seat files in the pull's way with an `mv` line, also printed. join.py takes the desk's repo id when the clone's .blueprints.toml has none. The new HARD line is rule text the person pastes in /permissions, not code. Rule 10 lets auto mode run the person's own bootstrap script from their private desk at the commit a pasted hand-off names: a real widening, and user-wide once pasted, so the person's call; this clone is seated and needs no bootstrap. Rule 11 lets a seat with a written push grant push fast-forward to its own origin, no force, no remote changes: no wider than this seat's own grant. No new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.118 (hard; desk #110 now asks for v0.1.118, pin stays) | the same 5 hard lines as v0.1.117 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); one new READ, the new file classes/triage/triage_conf.py | The v0.1.88 → v0.1.117 reads above, then the v0.1.117 → v0.1.118 diff outside docs/ and tests/ (9 files): the triage scripts (item-next.py, triage-archive.py, triage-state.py, the new triage_conf.py), the triage, builder and LOOP role texts, CLAUDE.md | Safe here; this seat runs no triage script. triage_conf.py reads the clone's own tracked `.blueprints.toml` `[triage]` table for document paths (environment first), runs only `git worktree list`, no network, no logins. A path in that table is resolved against the clone's root and could point outside it; it is the repo's own tracked file, so it carries the repo's own trust. |
| 2026-11-04 | v0.1.88 → v0.1.119 (hard; desk #110 now asks for v0.1.119, pin stays) | the same 5 hard lines as v0.1.118 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); no other finding changed | The v0.1.88 → v0.1.118 reads above, then the v0.1.118 → v0.1.119 diff outside docs/ and tests/ (3 files): drivers/git/watch-remote.sh, CLAUDE.md, plugin.json | Safe here. watch-remote.sh gains `--tags` (say tag lines only, skip trunk commits) and `--tag-pattern ERE` (a `grep -E` filter, checked as an ERE, no space or tab), with their own state file under the clone's git dir; it still only reads the remote the watcher already fetches. No new host, no writes outside that state; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.120 (hard; desk #110 now asks for v0.1.120, pin stays) | the same 5 hard lines as v0.1.119 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); one new READ, the new file classes/presenter/diagrams.py | The v0.1.88 → v0.1.119 reads above, then the v0.1.119 → v0.1.120 diff outside docs/ and tests/ (7 files): classes/base/nightly.py, classes/presenter/diagrams.py, classes/triage/item-next.py, LOOP.md, CLAUDE.md, the kit's own .blueprints.toml, plugin.json | Safe here; this repo runs no presenter seat. diagrams.py only reads git (`git show`, `ls-tree`, `rev-parse`, `cat-file` on origin/main) and prints the pages whose sources moved; nightly.py's new fifth job `diagrams` runs it and wakes a presenter only when it lists something, and only where a seat's `watch.nightly` names it (the kit's own config does, ours does not). item-next.py also counts a paged index's sibling files. No network, no new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.121 (hard; desk #110 now asks for v0.1.121, pin stays) | the same 5 hard lines as v0.1.120 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); the watchdog.py READ lines only renumbered | The v0.1.88 → v0.1.120 reads above, then the v0.1.120 → v0.1.121 diff outside docs/ and tests/ (5 files): classes/base/watchdog.py, classes/desk/stats.py, classes/presenter/diagrams.py, CLAUDE.md, plugin.json | Safe here. The watchdog holds a per-seat `<seat>.wake.lock` (flock in the local rack) from a wake's listing to its record, and the prompt hook waits up to 20 s on it, so a message is not listed twice. It records `away` and `back` moments in the local ledger's stream `presence` (repo, seat, session id and a fixed phrase for how; no message text), through the kit's own ledger.sh. stats.py changes wording only; diagrams.py may read one top-level Python definition from git. No new network call, no new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.122 (hard; desk #110 now asks for v0.1.122, pin stays) | the same 5 hard lines as v0.1.121 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); one new READ, the new file agents/fault-finder.md | The v0.1.88 → v0.1.121 reads above, then the v0.1.121 → v0.1.122 diff outside docs/ and tests/ (9 files): agents/fault-finder.md, classes/desk/watch-answers.py and answers.py, the desk's EDGES.md and PROTOCOL.md, CLAUDE.md, the kit's own pyproject.toml and uv.lock (hypothesis in its dev group), plugin.json | Safe here; nothing runs by itself. fault-finder is a new plugin agent (Opus, tools Bash, Read, Grep, Glob) that models one flow, runs TLC and Hypothesis tests in a scratch folder, and on a filing run files each finding on the kit's issues through report-to-kit's leak gate. It runs only when a session spawns it; on this repo only on the person's word, since a filing run would describe this repo's code on the kit's tracker. The desk watcher keeps an answer's key through a revision's window: desk reads only, no new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.123 (hard; desk #110 now asks for v0.1.123, pin stays) | the same 5 hard lines as v0.1.122 (repo-rename:42, host-move:124, onboard.py:979 and :987, AUTOMODE.md:143); no other finding changed | The v0.1.88 → v0.1.122 reads above, then the v0.1.122 → v0.1.123 diff outside docs/ and tests/ (4 files): drivers/git/watch-remote.sh, classes/builder/release-texts.py, scripts/wake-corpus.py, plugin.json | Safe here. The trunk, tag and release-texts watchers say a refused fetch only after 15 minutes of refusals, at most once an hour unless the error text changes, keeping since, last-said and the error text in a small local state file (`refused` in the watcher's state dir under the clone's git dir, release-texts.refused beside its said file). wake-corpus.py refuses a labels file naming one wake twice. No new fetch, no new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.124 (hard; desk #110 now asks for v0.1.124, pin stays) | the same 5 hard lines, the onboard.py two now at :985 and :993 (repo-rename:42, host-move:124, AUTOMODE.md:143); the other changes are renumbered READ lines | The v0.1.88 → v0.1.123 reads above, then the v0.1.123 → v0.1.124 diff outside docs/ and tests/ (10 files): bin/onboard.py, classes/base/watchdog.py, classes/desk/watch-answers.py, classes/presenter/diagrams.py, drivers/git/watch-remote.sh, mods/seats/register.tsx and its test, rules/WAKE_LABELS.md, CLAUDE.md, plugin.json | Safe here; each change turns a silent skip into a said unknown. `watchdog.py loaded` exits 3 with a reason where a repo declares seats but its settings or rack cannot be read; the UI mod shows a local toast with that exit and its first line. onboard.py says unknown when `git ls-files --others` fails; watch-remote.sh `--removes` flags an unreadable diff; the desk watcher matches a seat's relay by its own answer line. No new network call, no new host; nothing reads the logins. |
| 2026-11-04 | v0.1.88 → v0.1.124 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21; the five hard lines accepted by the person, desk #110 comment 6637218216) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-04 | v0.1.124 → v0.1.125 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-04 | v0.1.125 → v0.1.127 (read) | 1 READ, classes/base/BASE.md:91, the word "secret" in prose | The v0.1.125 → v0.1.127 diff outside docs/ and tests/ in full (16 files): classes/base/watchdog.py, nightly.py, BASE.md, classes/triage/item-next.py, triage-archive.py, triage_conf.py, drivers/leaves/relay.sh, drivers/zulip/plugin.py, rules/AUTOMODE.md, skills/report-to-kit/SKILL.md, agents/consensus.md, the builder, liaison and triage role texts, CLAUDE.md, plugin.json | Safe here. BASE.md:91 is prose: seats file kit reports without asking, at once when one touches security. The watchdog wakes a seat for an answer, within 8 h, in the topic or DM it posted to through `send`, read from the local ledger, and says when the 5-hour window goes back on pace; the Zulip plugin records a message's channel and topic. nightly.py adds a weekly `deps` job for liaison seats (this repo runs none). triage_conf.py runs `git rev-parse --show-toplevel` so the archiver resolves its worktree; item-next.py scans local .md files. relay.sh restarts a stalled relay run once within its timeout. AUTOMODE rules 11 and 12 are text the person pastes, nothing runs them. No new host, no new process beyond git, no persistence; nothing reads the logins. |
| 2026-11-04 | v0.1.125 → v0.1.127 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-05 | v0.1.127 → v0.1.128 (hard; pin stays, put to the person) | 1 HARD, bin/onboard.py:1080 `| sh -s {names}{' --overlay' if over else ''}`: the accepted `| sh -s {names} --overlay` line, merged with its non-overlay twin into one f-string | The v0.1.127 → v0.1.128 diff outside docs/ and tests/ in full (9 files): bin/onboard.py, bin/move-to-tag.py, scripts/seats.py, rules/AUTOMODE.md, classes/builder/BUILDER.md, classes/triage/LOOP.md, CLAUDE.md, the kit's own .blueprints.toml, plugin.json | Safe here. The flagged line is text onboard.py prints for the person to run in a terminal (the desk's bootstrap at a pinned commit sha, piped to sh), as before; the kit runs nothing from it. New in onboard.py: after opening the seats' pull requests it asks once on /dev/tty (or $ONBOARD_ANSWER) and, on `m`, merges them with `gh pr merge`, then deletes each `seat/<seat>` branch on origin and pulls; run only by the person during onboarding, never in this repo's seat. seats.py and onboard.py gain `--desk-id` for a repo the desk files under another id. move-to-tag.py reports a plugin still starting instead of failing. AUTOMODE rule 5 is text the person pastes. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.129 (hard; desk #197 now asks for v0.1.129, pin stays) | the same 1 HARD line as v0.1.128, now bin/onboard.py:1103 | The v0.1.127 → v0.1.128 read above, then the v0.1.128 → v0.1.129 diff outside docs/ and tests/ (11 files): bin/onboard.py, drivers/claude-code/bootstrap.sh.in, drivers/slurm/digest-jobs.sh, facts.sh, slurm.toml.example, scripts/seats.py, rules/AUTOMODE.md, skills/onboard/SKILL.md, the admin and builder role texts, plugin.json | Safe here. onboard.py asks its merge question on the first terminal it can open (raw read/write on /dev/tty or the tty of fd 2/1/0) and takes `--merge` to answer `m` up front; bootstrap.sh passes `--merge` through and prints a note on where the pin lives. The slurm driver resolves its job-name prefix from repo or machine config through the kit's conf.sh (this repo runs no slurm seat). seats.py lists the Zulip organisation's members (GET /users, the server it already talks to) so it never invites an address that already has an account. AUTOMODE rule 2 is pasted text. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.130 (hard; desk #197 now asks for v0.1.130, pin stays) | the same 1 HARD line as v0.1.129, bin/onboard.py:1103 | The v0.1.127 → v0.1.129 read above, then the v0.1.129 → v0.1.130 diff outside docs/ and tests/ (4 files): classes/triage/item-next.py, classes/triage/LOOP.md, rules/AUTOMODE.md, plugin.json | Safe here. item-next.py also reads the trunk's committed markdown (origin/HEAD and the local branch of that name) through local `git ls-tree`/`cat-file`, nothing fetched, so a reservation committed on the trunk is not handed out again; this repo runs no triage seat. AUTOMODE rule 3 is pasted text that now describes what `bin/move-to-tag.py` does. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.131 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line as v0.1.130, bin/onboard.py:1103 | The v0.1.127 → v0.1.130 read above, then the v0.1.130 → v0.1.131 diff outside docs/ and tests/ (4 files): drivers/leaves/relay.sh, agents/consensus.md, classes/builder/BUILDER.md, plugin.json | Safe here, and narrower than before: relay.sh withholds the widening flags three outside-model relays add by default (Cursor gets `--no-force`, commandcode and omp `--read-only`) and gives each run its own TMPDIR under its output folder, removed after; the consensus agent snapshots `git status --porcelain --ignored` before and after its runs to report files a run wrote into the repository. BUILDER.md is prose for lead seats. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.132 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line as v0.1.131, bin/onboard.py:1103 | The v0.1.127 → v0.1.131 read above, then the v0.1.131 → v0.1.132 diff outside docs/ and tests/ (5 files): bin/land.sh, classes/lead/plan-watch.py, rules/AUTOMODE.md, CLAUDE.md, plugin.json | Safe here. land.sh gains `--wait MINUTES`: a failed fetch or a refused push to origin is retried every 30 s until the time is up (same remote, same push, no force). plan-watch.py stops flagging the heading item-next anchors on, reading the anchor from the kit's own triage_conf. AUTOMODE rule 1 is pasted text that now also allows post.py on a seat's own desk questions. This repo uses none of land.sh or plan-watch. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.133 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line as v0.1.132, bin/onboard.py:1103 | The v0.1.127 → v0.1.132 read above, then the v0.1.132 → v0.1.133 diff outside docs/ and tests/ (3 files): classes/triage/item-next.py, classes/lead/plan-watch.py, plugin.json | Safe here. item-next's `written()` also reads the trunk's committed markdown through the same local `committed()` added in v0.1.130 (no fetch); plan-watch reports an anchor it cannot load instead of guessing. This repo uses neither. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.134 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line as v0.1.133, bin/onboard.py:1103; 1 READ, rules/AUTOMODE.md:155 (network: `gh release create`) | The v0.1.127 → v0.1.133 read above, then the v0.1.133 → v0.1.134 diff outside docs/ and tests/ (2 files): rules/AUTOMODE.md, plugin.json | Safe here. No code changed: AUTOMODE rule 13 is new allow-list text, pasted by the person, letting a seat whose priming grants version tags and whose release cycle says so run `gh release create/edit` on its own repository's pushed tag. It widens what such a seat may publish; this seat's grant names no release (releases stay the person's), so nothing here would use it. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.135 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line as v0.1.134, bin/onboard.py:1103; 1 READ, rules/AUTOMODE.md:155 (network: `gh release`) | The v0.1.127 → v0.1.134 read above, then the v0.1.134 → v0.1.135 diff outside docs/ and tests/ (2 files): rules/AUTOMODE.md, plugin.json | Safe here. No code changed: AUTOMODE rule 13 revision 2 also lets such a seat attach the wheel and sdist it built from the tag in a clean checkout (`gh release upload`, no `--clobber`, no package index). This seat's grant names no release, so nothing here would use it. No new host; nothing reads the logins. |
| 2026-11-05 | v0.1.127 → v0.1.136 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line and 1 READ (AUTOMODE rule 13) as v0.1.135 | The v0.1.127 → v0.1.135 read above, then the v0.1.135 → v0.1.136 diff outside docs/ and tests/ (4 files): classes/base/watchdog.py, classes/base/BASE.md, classes/base/EDGES.md, plugin.json | Safe here. watchdog.py keeps the path of the client's per-session env file (CLAUDE_ENV_FILE) in `<sessions dir>/<sid>.env`, deleted with the session's card when it goes dark, and at Stop, PreCompact and each prompt appends `export BLUEPRINTS_KIT='<kit copy>'` to that same file when it names another copy, so a session reloaded onto a newer kit runs the newer scripts. Local files the client already gives the hook; no new host, process or persistence outside the kit's own state. BASE.md: in a clone shared by seats, commit with `git commit --only -- <paths>` (this repo has one seat). Nothing reads the logins. |
| 2026-11-06 | v0.1.127 → v0.1.137 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line and 1 READ (AUTOMODE rule 13) as v0.1.136 | The v0.1.127 → v0.1.136 read above, then the v0.1.136 → v0.1.137 diff outside docs/ and tests/ (4 files): drivers/git/watch-remote.sh, classes/liaison/watch-upstream.sh, classes/liaison/LIAISON.md, plugin.json | Safe here. watch-remote.sh takes `--any-tagger`, which clears the clone's own identity so a tag it made is reported too; watch-upstream.sh always passes it. A flag for watchers only, no new git operation. This repo declares neither script (its only watcher is `scripts/kittrack.py watch`). LIAISON.md is another role's prose. No new host; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.138 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line and 1 READ (AUTOMODE rule 13) as v0.1.137 | The v0.1.127 → v0.1.137 read above, then the v0.1.137 → v0.1.138 diff outside docs/ and tests/ (7 files): bin/release.py, bin/plan-state.sh, classes/triage/item-next.py, CLAUDE.md, classes/builder/BUILDER.md, classes/liaison/LIAISON.md, plugin.json | Safe here. release.py (the kit's own release tool) gains `--wait MINUTES`: a busy machine or another release's hold is retried every 30 s, re-fetching the same origin, before it holds anything. plan-state.sh also takes lead and builder inbox ids (L/B), writing docs/LEAD_INBOX.md or docs/BUILDER_INBOX.md. item-next.py drops one extra blank line on a release. The rest is other roles' prose. This repo uses none of them. No new host; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.139 (hard; desk #197 covers it as "the newest", pin stays) | the same 1 HARD line and 1 READ (AUTOMODE rule 13) as v0.1.138 | The v0.1.127 → v0.1.138 read above, then the v0.1.138 → v0.1.139 diff outside docs/ and tests/ (3 files): drivers/git/watch-remote.sh, classes/builder/BUILDER.md, plugin.json | Safe here. watch-remote.sh under `--tags` now reports tags whatever their tagger (a one-line condition on the identity skip); the builder's prose follows. This repo declares no such watcher. No new host; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.140 (hard; desk #197 now asks for two lines, pin stays) | 2 HARD: the bin/onboard.py:1103 line of v0.1.139, and a new one, scripts/wake-corpus.py:93 `BUTTON = re.compile(r"watchdog\.(?:py|sh)\S*\s+nothing\b")`, the gate's `\| *(ba)?sh\b` matching `|sh)` inside a regex alternation; 1 READ (AUTOMODE rule 13) as before | The v0.1.127 → v0.1.139 read above, then the v0.1.139 → v0.1.140 diff outside docs/ and tests/ (5 files): classes/base/watchdog.py, scripts/wake-corpus.py, agents/consensus.md, agents/trunk-review.md, plugin.json | Safe here. The new hard line is a false positive: a Python regex that recognises the seat's `watchdog.py|sh nothing` command in transcripts, no pipe and no shell. watchdog.py shortens its wake hints to `watchdog.sh ...` and folds them into one footer line. The consensus and trunk-review agents locate the pinned kit copy with `bin/move-to-tag.py --copy` instead of `$BLUEPRINTS_KIT`, so an older copy's relay never runs an outside model widened. No new host; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.141 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.140 (onboard.py:1103, wake-corpus.py:93); READ: AUTOMODE rule 13 as before, the word "token" in ledger.py:219-226 and watchdog.py:1933 (a message's short id, no credential), watchdog.py:4109 (the wake socket, unchanged in kind), new files bin/kit-run.sh and skills/kit-tools/SKILL.md | The v0.1.127 → v0.1.140 read above, then the v0.1.140 → v0.1.141 diff outside docs/ and tests/ (14 files) in full: classes/base/watchdog.py, classes/base/ledger.py, drivers/herdr/reload.py, bin/kit-run.sh, bin/seats-export.py and its schema, mods/seats/register.tsx, types/index.d.ts, scripts/wake-corpus.py, classes/base/BASE.md, skills/kit-tools/SKILL.md, CLAUDE.md, plugin.json | Safe here. Short message ids: a 6-hex SHA-1 handle or the messenger's own number, resolved among the held seat's messages and refused when ambiguous. `watchdog.py reload [--mcp]` starts the existing herdr typer detached for the session's own pane only, with one of two fixed texts (`/reload-plugins`, `/mcp reconnect all`), under the same idle/unfocused/empty-line checks, now behind a machine-wide flock in $XDG_RUNTIME_DIR. kit-run.sh runs a kit .py/.sh from the pinned copy, refusing absolute paths and `..`. seats-export lists declared seats with no card, reading .blueprints.toml and the clone's git dir for a first-seating handout file; the seats pane shows them. No new host; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.142 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.141 (onboard.py, now at :1149, text unchanged; wake-corpus.py:93); READ: the word "token" in ledger.py and watchdog.py as before, drivers/zulip/plugin.py:1155 (a new https fetch, below), drivers/cursor/draw.sh (new), six new agent skills | The v0.1.127 → v0.1.141 read above, then the v0.1.141 → v0.1.142 diff outside docs/ and tests/ (28 files): the code in full (bin/onboard.py, bin/overlay.py, bin/release.py, classes/base/nightly.py, classes/base/watchdog.py, drivers/cursor/draw.sh, drivers/herdr/reload.py, drivers/zulip/plugin.py, scripts/seats.py, .claude/settings.json, .blueprints.toml); the prose (CLAUDE.md, role texts, skills, commands/seat.md) swept for addresses and for hooks, settings, pipes to a shell, cron or login items: none | Safe here. Seat pictures: `watchdog.py avatar SEAT --roster` lists every seat account's picture, fetching one the messenger names over https with no credential sent when it is stored off the messenger's server (a picture host the organisation chose); `--draw TEXT` runs Cursor's agent sandboxed in an empty folder to draw one. Both run only when a seat asks; this seat does not. seats.py gains `seating` and `gaps` (subscriptions, the administrator key's machine only), run daily by the kit's own tooling seat (nightly.py subs); release.py posts its own announcement. overlay.py gains place --master, track and untrack, person-run onboarding tools. reload.py hands `/mcp reconnect all` to a herdr plugin from 0.1.1. The kit repo's own .claude/settings.json enables four official plugins for its own clone; nothing is installed here. No new host this repo reaches; nothing reads the logins. |
| 2026-11-07 | v0.1.127 → v0.1.143 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.142 (onboard.py, now at :1165, text unchanged; wake-corpus.py:93); READ: AUTOMODE gains rule 14, text for the person to paste, not applied here | The v0.1.127 → v0.1.142 read above, then the v0.1.142 → v0.1.143 diff outside docs/ and tests/ (24 files): the code in full (bin/onboard.py, bin/overlay.py, classes/base/nightly.py, classes/base/watchdog.py, classes/desk/deskfile.py, export.py and its schema, queue.py, the desk template's three files, drivers/zulip/plugin.py, .blueprints.toml, rules/AUTOMODE.md); the prose (README.md, CLAUDE.md, skills/onboard/, skills/kit-tools/, classes/desk/PROTOCOL.md and SECRETARY.md, BUILDER.md) swept for addresses and for hooks, settings, pipes to a shell, cron or login items: none | Safe here. Wake rules: a seat may name `wake_topics` (channel>topic) whose seat posts wake it; an announcement that mentions the seat or the channel wakes it whoever posted, since the admin seat is retired. nightly.py subs now runs only where the administrator key file is. The desk reads two new repos.toml keys, `overlay` and `desk` (followed desks named in the queue). watchdog.py retire frees an account of a seat dropped from the table, from a pool the table names. Rule 14 lets a seat's own `watchdog.sh reload` type `/reload-plugins` or `/mcp reconnect all` into its own pane, as v0.1.141's typer already did. No new host; nothing reads the logins. |
| 2026-11-08 | v0.1.127 → v0.1.144 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.143 (onboard.py, now at :1167, text unchanged; wake-corpus.py:93) | The v0.1.127 → v0.1.143 read above, then the v0.1.143 → v0.1.144 diff outside docs/ and tests/ (3 files) in full: bin/onboard.py, classes/base/digest.py, plugin.json | Safe here. onboard.py's messages name `seats.py seating` and the key's holder instead of the retired admin seat. The digest's stale-memory check no longer flags a path that still exists at the tip of a local or fetched branch (read-only `git for-each-ref` and `git cat-file --batch-check`). No new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.145 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.144 (onboard.py:1167, wake-corpus.py:93); READ: the word "token" in ledger.py as before; AUTOMODE rule 1 widened (text for the person to paste, not applied here) | The v0.1.127 → v0.1.144 read above, then the v0.1.144 → v0.1.145 diff outside docs/ and tests/ (27 files): the code in full (.blueprints.toml, bin/automode.py, bin/kit-run.sh, bin/move-to-tag.py, classes/base/nightly.py, classes/base/watchdog.py, classes/desk/post.py, drivers/claude-code/mcp-check.py (new), drivers/herdr/reload.py, drivers/zulip/last-seen.py, scripts/seats.py, rules/AUTOMODE.md, commands/retire.md); the prose (README.md, CLAUDE.md, BASE.md, LEAD.md, BUILDER.md, the correspondence role renamed from devrel, PROTOCOL.md, rules/WATCHERS.md, skills/onboard/ and kit-tools/) read for addresses and for hooks, settings, pipes to a shell, cron or login items: only a `https://<name>.zulipchat.com` placeholder in the adoption wizard's prose | Safe here. mcp-check.py reads the Claude client's own MCP logs under ~/.cache/claude-cli-nodejs for this session and, when a server timed out, has the existing herdr typer type `/mcp reconnect all` into the seat's own pane; the watchdog starts it detached after a resume or a reload. A `presence = false` seat table key makes a quiet seat (not set here). nightly.py gains a job `dark` (seats unseen 14 days, read from the messenger and `gh issue list` on the desk; not declared here). post.py --relabel moves a taken-over question's seat: label. last-seen.py --repo, seats.py's shared-channel making, kit-run.sh running bash scripts with bash, move-to-tag.py leaving the reload to the typer in a herdr pane. No new host this repo reaches; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.146 (hard; desk #197 covers it as "the newest", pin stays) | the same 2 HARD lines as v0.1.145 (onboard.py:1167, wake-corpus.py:93); READ: inbox.py's new proxy socket code, the word "token" in ledger.py as before | The v0.1.127 → v0.1.145 read above, then the v0.1.145 → v0.1.146 diff outside docs/ and tests/ (6 files) in full: scripts/inbox.py now reaches the IMAP mailbox through an HTTP CONNECT to the proxy HTTPS_PROXY/https_proxy names, unless NO_PROXY covers the host. It sends Basic proxy credentials only from that URL, to that proxy, and opens no other host; bin/release.py `--busy` (the kit's own release on a loaded machine); PROTOCOL.md/SECRETARY.md say the typer or `watchdog.sh reload` types `/reload-plugins` in a herdr pane; docs and tests swept: only 127.0.0.1 proxies in test_inbox.py. Safe here: inbox.py is never run by this repo. No new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.147 (hard; 3 new lines, put on desk #197 as an Update, comment 6735560948; pin stays) | the 2 HARD lines as before (onboard.py:1167, wake-corpus.py:93) and 3 new HARD "persistence" lines in classes/desk/template/setup.sh:80, 81, 92: `echo` lines that print the desk mover's crontab instructions for the person ("Then install its mover ... (crontab -e)", "shell's environment, so put these lines at the top of the crontab ...", "A host that refuses a user crontab ...") | The v0.1.127 → v0.1.146 read above, then the v0.1.146 → v0.1.147 diff outside docs/ and tests/ (13 files) in full. setup.sh prints the PATH, XDG_CONFIG_HOME, XDG_STATE_HOME, GH_CONFIG_DIR and BLUEPRINTS_PYTHON lines for the person to paste, never the proxy variables, and installs nothing. watchdog.py adds a read-only `received` listing from the local ledger, marks the MCP check's unknown as said only once it is delivered, and has retake keep the seat when a plugin misses its start wait; pool_holds and plugin.py machine_path read a ~/.config pool under $XDG_CONFIG_HOME. seats.py `unticket` joins a desk ticket back into the pool (onboard.take_ticket) and retires it to a spare. nightly.py dark judges each account of a seat; herdr reload.py says why it waited; mcp-check.py records unknown on any exception; inbox.py no longer prints a proxy URL's login; release.py --busy says a stale load; PROTOCOL.md cron lines go through bin/py.sh. Docs and tests swept: only example and 127.0.0.1 proxies. Safe here: the setup.sh lines are text printed for the person, run only when a desk is set up, never by this repo. No new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.148 (hard; desk #197 covers it since its fourth Update, as "the newest"; pin stays) | the same 5 HARD lines as v0.1.147 (onboard.py:1167, wake-corpus.py:93, setup.sh:80, 81, 92) | The v0.1.127 → v0.1.147 read above, then the v0.1.147 → v0.1.148 diff outside docs/ and tests/ (13 files) in full. New: `bin/automode.py --apply` writes the person's ~/.claude/settings.json, but only the autoMode allow entries headed `Agent seats kit, rule N`, taken from the kit's rules/AUTOMODE.md. It never writes the environment entry, permission rules or hooks, keeps a settings.json.automode.bak and refuses a file that changed while read. AUTOMODE rule 15 (the person's yes, 2026-11-09) lets a session run it; nothing in the watchdog or the hooks runs it, and the digest only prints the command. This seat does not run it unasked. `seats.py releases --apply` reads the kit's tags with `gh api` and posts missing release announcements to Zulip with the admin key, hourly from nightly.py's subs job. That job runs only under the desk secretary's watcher on the key's machine (this machine has seats.env), at the desk's own pin, not this repo's. Also changed: py.sh tries python3.19 down to 3.11; mcp-check.py counts servers connected before a reload, reading /proc/stat btime and the card's start ticks; watchdog's digest wording. Docs, skills and tests swept: no new URL or risky word. Safe here: no new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.149 (hard; desk #197 covers it as "the newest"; pin stays) | the same 5 HARD lines as v0.1.148 (onboard.py:1167, wake-corpus.py:93, setup.sh:80, 81, 92) | The v0.1.127 → v0.1.148 read above, then the v0.1.148 → v0.1.149 diff outside docs/ and tests/ (16 files) in full. New: `watchdog.sh attachments ID [--out DIR]` saves a received message's files only when the seat's holder asks, and only from `/user_uploads/` links in the message. It fetches through plugin.py's `fetch`, which refuses any URL off the account's own Zulip server and caps each file at 25 MiB. Files keep their base name only, so no path escapes the folder, which defaults to ~/.local/state/agent-seat-blueprints/attachments/, mode 0700. Nothing runs them. Listings mark `[files: …]`. `seats.py channel` makes a Zulip channel with the admin key. The desk template's secretary `wake_from` gains `*/*`, so any seat may wake it. AUTOMODE rule 3 adds attachments; rule 4 moves the Zulip admin grant to the desk secretary; both are text for the person to paste or apply, not applied here. Docs, skills and tests swept: no new URL or risky word. Safe here: no new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.150 (hard; desk #197 covers it as "the newest"; pin stays) | the same 5 HARD lines as v0.1.149 (onboard.py:1167, wake-corpus.py:93, setup.sh:80, 81, 92) | The v0.1.127 → v0.1.149 read above, then the v0.1.149 → v0.1.150 diff outside docs/ and tests/ (5 files) in full. New: `seats.py unheard` uses the Zulip admin key to read the last 6 hours of channel posts, finds a person's mention of a seat that no seat reacted to or answered within 15 minutes, and prints each with the seat account's state. It writes nothing on the server. nightly.py's subs job runs it every 15 minutes, only on the admin key's machine (seats.env) under the desk secretary's watcher, at the desk's pin, not this repo's. The kit's own .blueprints.toml drops the tooling seat's subs watcher. Docs and tests swept: only chat.example.test in a test. Safe here: no new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.151 (hard; desk #197 covers it as "the newest"; pin stays) | the same 5 HARD lines as v0.1.150 (onboard.py:1167, wake-corpus.py:93, setup.sh:80, 81, 92) | The v0.1.127 → v0.1.150 read above, then the v0.1.150 → v0.1.151 diff outside docs/ and tests/ (6 files) in full. herdr reload.py rereads the input line for about 3 s and sends Enter to its own text left from an earlier try; it still types only `/reload-plugins` or `/mcp reconnect all`. watchdog.py claims the reload record under the MCP lock and explains why a short id is ambiguous. last-seen.py and nightly.py dark mark one unreadable account unknown. SECRETARY.md is prose. Docs and tests swept: no new URL or risky word. Safe here: no new host; nothing reads the logins. |
| 2026-11-09 | v0.1.127 → v0.1.152 (hard; desk #197 covers it as "the newest"; pin stays) | the same 5 HARD lines as v0.1.151, with the same text; the setup.sh ones moved to lines 82, 83, 94 (onboard.py:1167, wake-corpus.py:93) | The v0.1.127 → v0.1.151 read above, then the v0.1.151 → v0.1.152 diff outside docs/ and tests/ (16 files) in full. `bin/automode.py --apply` now also writes the person's autoMode environment entry in ~/.claude/settings.json, as one block between BEGIN and END marker items. It removes the kit's older entry, leaves the person's other items, keeps the .bak and refuses markers out of order. AUTOMODE rule 15 still says the script never writes the environment entry, so it understates the write. Filed on the kit as #340; this seat does not run --apply unasked. New rule 16 is text for the kit's report-to-kit filing; rule 11 now counts read-only git around a push as the same push. Both are text for the person to apply. The desk template adds a secretary watcher on the kit's release tags (`drivers/git/watch-remote.sh`), and setup.sh writes the kit path as `~/...`. drivers/watch/plugin.py expands a `~/` word in a watcher command; watch-kit.sh handles a detached kit checkout; move-to-tag.py rereads a torn card. Docs and tests swept: no new URL or risky word. Safe here: no new host; nothing reads the logins. |
| 2026-11-10 | v0.1.127 → v0.1.153 (moved: the 5 hard lines accepted under the person's grant of 2026-11-09, desk #197) | the same 5 HARD lines as v0.1.152 (onboard.py:1167, wake-corpus.py:93, setup.sh:82, 83, 94), now listed in scripts/kitgate-accepted.txt; then 82 READ items | The v0.1.127 → v0.1.152 read above, then the v0.1.152 → v0.1.153 diff outside docs/ and tests/ (25 files): hooks.json, automode.py, AUTOMODE.md, report-to-kit.py, mcp-check.py and ledger.py in full; watchdog.py, plugin.py, seats.py, nightly.py, the new bin/seat-rename.py and the desk template swept for processes, network, credentials and persistence | Safe here. hooks.json adds a fourth SessionStart line printing the base's fourth part (`watchdog.py base 4`). seat-rename.py renames a seat in the repo's own files through local git only. The watchdog reacts `eyes` to a person's message once shown to the session (receipt) and says an unanswered one once more after 30 min, through the existing Zulip driver. report-to-kit.py adds an `**Asked by:**` line, checked by the same leak gate. mcp-check.py records "not needed" when no MCP server ever logged for the session. automode.py reads a seat's `role` key (D165). AUTOMODE rule 15 revision 2 now names the environment-block write (kit #340 answered). Docs and tests swept: only test placeholders. No new host; nothing reads the logins. |
| 2026-11-10 | v0.1.127 → v0.1.153 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09 (desk #197)) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.153 → v0.1.154 (moved: the 1 hard line accepted by the seat under the person's grant of 2026-11-09) | 1 HARD, new network host `github`: bin/move-to-tag.py:307, `re.sub(r"^https://github\.com/` … `", "", repo)`, the gate's host pattern stopping at the escaped dot; now listed in scripts/kitgate-accepted.txt, which takes a host from 2e44ebb | The v0.1.153 → v0.1.154 diff outside docs/ and tests/ (26 files): hooks.json, hooks/question-gate.sh (new), AUTOMODE.md, until-event.sh and move-to-tag.py's machine pin in full; watchdog.py, nightly.py, seats.py, herdr reload.py, the new drivers/zulip/embassy.py, report-to-kit.py, seat-rename.py and the desk template swept for processes, network, credentials and persistence | Safe here. question-gate.sh, a new PreToolUse hook on AskUserQuestion, denies the question dialog to a seated session (or every session on a cluster site) and says to ask in the messenger or on the desk; it reads only the seat cards, fails closed and blocks nothing else. move-to-tag.py `--machine TAG` moves the user-scope pin in ~/.claude/settings.json through the client's own plugin commands, when the person runs it; this repo's pin is the clone's own, which wins. report-to-kit.py also reads the user settings to find the kit's repository. embassy.py routes OpenPGP ciphertext between two chat organisations, under the desk secretary only; not run here. The herdr typer learns tmux and screen panes (rule 14 widened to match). No new host this repo reaches; nothing reads the logins. |
| 2026-11-10 | v0.1.153 → v0.1.154 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.154 → v0.1.155 (moved: the 3 hard lines accepted by the seat under the person's grant of 2026-11-09) | 3 HARD "foreign secret": classes/base/seatkeys.py:23, 328, 351, the word "keyring" of a seat's own GnuPG home; now listed in scripts/kitgate-accepted.txt | The v0.1.154 → v0.1.155 diff outside docs/ and tests/ (8 files): seatkeys.py (new) in its gpg calls and paths; watchdog.py, plugin.py, seats.py and ledger.py swept for processes, network, credentials and persistence | Safe here. End-to-end encrypted seat messages (D167): seatkeys.py runs gpg with `--homedir` set to a per-seat home under $XDG_STATE_HOME/agent-seat-blueprints/keys/, mode 700, never ~/.gnupg; keys exist only after `watchdog.py keys init`, which this seat has not run; the watchdog's daily look rotates a subkey only where keys exist. `send --encrypt` posts ciphertext through the same Zulip driver; the plugin decrypts what reaches the seat. gpg is optional. No new host; nothing reads the logins. |
| 2026-11-10 | v0.1.154 → v0.1.155 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.155 → v0.1.156 | 1 read (the plugin's manifest) | The v0.1.155 → v0.1.156 diff outside docs/ and tests/ (8 files) in full: classes/desk/forge.py, export.py and its schema, drivers/herdr/reload.py; PROTOCOL.md, SECRETARY.md and ORG.md as prose | Safe here. The desk credits an `**Answer:**` posted under a collaborator's own login to that login (an `**Answered by:**` line), so it waits out the owner's objection window; export.py carries each inbox file's From line. The herdr typer reads the per-seat turn mark older hooks keep, beside the seat's card, when a session has no mark of its own. No new host; nothing reads the logins. |
| 2026-11-10 | v0.1.155 → v0.1.156 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.156 → v0.1.157 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.157 → v0.1.158 (the 3 hard lines accepted by the seat under the person's grant of 2026-11-09) | 3 HARD persistence: classes/desk/template/setup.sh:84, 85, 98, echo lines printing the cron fallback for a desk's mover; now listed in scripts/kitgate-accepted.txt; 14 read (credential, network, 2 new files) | The v0.1.157 → v0.1.158 diff outside docs/ and tests/ (42 files): orgconf.py (new) and mover.sh (new) in full; inbox.py/seats.py (`probe`, `mailbox`: a read-only IMAP login check, the password never printed; config path via orgconf); plugin.py (`_take`/`_taken`/`elsewhere`: a seat-take direct message on the person's own Zulip, read with the machine's own pool keys); watchdog.py (org seats taken from any directory, a detached `who` of its own script); setup.sh as printed text | Safe here. mover.sh runs git pull/push and tick.py in a desk clone only, under the desk's secretary; nothing installs cron, a service or a hook; orgconf only chooses which folder under ~/.config/agent-seat-blueprints/ a tool reads. No new host, no download, no settings write. This repo has no org seat and no desk. |
| 2026-11-10 | v0.1.157 → v0.1.158 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.158 → v0.1.159 | 1 read (2 items: ORG.md's `gh api` line, classes/plumber/machine/seats.toml new) | The v0.1.158 → v0.1.159 diff outside docs/ and tests/ (17 files): seats.toml (new) in full, a template seat table with no command; onboard.py's `--user` (writes a seat table, priming and first.md only under ~/.config/agent-seat-blueprints/user/); ask.py, join.py, plugin.py, watchdog.py, move-to-tag.py, seats.py in their added lines; the onboarding texts as prose (ORG.md's `gh api` reads a desk's table through the forge, by hand) | Safe here. Organisation seats taken from any machine and a per-machine tooling seat; no new host, no download, no settings, cron or service write. This repo has neither seat. |
| 2026-11-10 | v0.1.158 → v0.1.159 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.159 → v0.1.160 | 1 read (24 items: credential words, `gh api` lines, bin/org-copy.py new) | The v0.1.159 → v0.1.160 diff outside docs/ and tests/ (21 files): org-copy.py (new) in full, a dry-run-by-default copy of a desk's seat table read through `gh api` into ~/.config/agent-seat-blueprints/org/<id>/; plugin.py's secret-shape filter (a message that looks like a key is held back, L104) and `--sensitive` sends; drivers/herdr/reload.py in its added lines (a fixed set of typed texts: /reload-plugins, /mcp reconnect all, /exit, /compact, /clear, then `/seats:seat NAME` with the name checked; never free text); watchdog.py, seatkeys.py, move-to-tag.py, seats.py, embassy.py and setup.sh (an `--id` check) in their added lines; the texts as prose | Safe here. No new host, no download, no settings, cron or service write; the typer's /exit runs on a seat's retire. This repo has no desk and no organisation seat. |
| 2026-11-10 | v0.1.159 → v0.1.160 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.160 → v0.1.161 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.161 → v0.1.162 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.162 → v0.1.163 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.163 → v0.1.164 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.164 → v0.1.165 | 1 read (4 items: two `socket.gethostname()` lines, classes/base/duties.py and classes/duties.toml new) | The v0.1.164 → v0.1.165 diff outside docs/ and tests/ (15 files): duties.py and duties.toml in full (a read-only catalogue of duties; roles as presets); watchdog.py's host name lines (a local site-id suggestion, nothing sent); automode.py, seat-rename.py, plugin.py in their added lines | Safe here. No new host, download, settings, cron or service write. The kit's pin mover is now keyed on the duty `pin-mover`, held by the tooling role only; this repo's seat `downstream` maps to role downstream, whose preset is empty, so no seat here holds it and this seat keeps the pin. |
| 2026-11-10 | v0.1.164 → v0.1.165 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.165 → v0.1.166 | 1 read (2 items: BASE.md's `--sensitive` lines) | The v0.1.165 → v0.1.166 diff outside docs/ and tests/ (6 files): BASE.md's new section "Another organisation" as prose; digest.py (a kit `sh kit:` command naming a bash script now runs under bash); the onboarding texts as prose | Safe here. No new host, download, settings, cron or service write. The base's rules for another organisation's messages do not reach this seat, which has no embassy. |
| 2026-11-10 | v0.1.165 → v0.1.166 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.166 → v0.1.167 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.167 → v0.1.168 (the 3 hard lines accepted by the seat under the person's grant of 2026-11-09) | 3 HARD pipe to shell: bin/onboard.py:1208 (the printed long line, `{flag}` now), commands/take.md:35 and skills/levers/SKILL.md:27 (prose naming that line); now listed in scripts/kitgate-accepted.txt; 7 read (seatkeys.py's secret-key listing, hooks/hooks.json, commands/take.md new) | The v0.1.167 → v0.1.168 diff outside docs/ and tests/ (14 files): commands/take.md (new) and onboard.py's `--take` in full; hooks.json (one more SessionStart hook, `watchdog.py base 5`, the same shape as parts 1-4); seatkeys.py's secret-key check (a local `gpg --list-secret-keys` on a seat's own home); the texts as prose | Safe here. `/seats:take` is a person-typed command: it refuses a seat already declared or pooled, then fetches the person's own desk's seating/bootstrap.sh at the commit that last changed it and runs it as `sh -s SEAT`, exactly the long line already accepted; nothing runs by itself. No new host, no settings, cron or service write. |
| 2026-11-10 | v0.1.167 → v0.1.168 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.168 → v0.1.169 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-10 | v0.1.169 → v0.1.170 (the 1 hard line accepted by the seat under the person's grant of 2026-11-09) | 1 HARD pipe to shell: skills/levers/SKILL.md:27 (the same prose row naming the desk's long line, its tail reworded for #396); now listed in scripts/kitgate-accepted.txt; 2 read | The v0.1.169 → v0.1.170 diff outside docs/ and tests/ (13 files): onboard.py `existing()` (a seat the clone declares with no pooled account is no longer refused, the bootstrap joins its ticket); watchdog.py (the reload typer finishes its own leftover `/reload-plugins` draft; an encrypted message's receipt also sent once answered; announcements and wildcard mentions no longer count as the person back); zulip plugin.py (a `wildcard` flag from Zulip's own flags); the texts as prose (SECRETARY.md seating a repository on its person's word, D182) | Safe here. No new host, command, settings, cron or service write; the take still runs only the person's own desk bootstrap on a person-typed command. |
| 2026-11-10 | v0.1.169 → v0.1.170 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.170 → v0.1.171 | 2 read, credential: scripts/inbox.py:154 and :240 (`fetch()` and its caller gain a `to` argument) | The v0.1.170 → v0.1.171 diff outside docs/ and tests/ (11 files): inbox.py's IMAP fetch, now optionally narrowed by a server-side `SEARCH TO` (quotes stripped from the address), the mailbox still opened read-only with BODY.PEEK; move-to-tag.py runs the new copy's own `automode.py --check` (read-only) after a take and prints its line; seats.py `mark --org` (marks the org's script account in the Zulip profile field, refusing a seat's); embassy.py says the plain posts already waiting at a router's first start; watchdog.py and zulip plugin.py label that org account; rules/AUTOMODE.md rule 15 reworded (revision 3) | Safe here. Same IMAP host and credentials as before, no new host; the only new subprocess is the kit's own read-only check. Rule 15's `--apply` is still left to the person in this seat. |
| 2026-11-11 | v0.1.170 → v0.1.171 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.171 → v0.1.172 | 17 read: drivers/herdr/panes.py (new); its tmux socket and herdr calls; seats.py's embassy handshake note and site-host checks; credential words in prose | The v0.1.171 → v0.1.172 diff outside docs/ and tests/ (16 files): panes.py in full (names the person's herdr tab or tmux window for the seats a session holds, puts it back at a stop; `start()` opens a new unfocused tab and runs `claude '/seats:seat NAME'` there); watchdog.py `start-session` (refused unless a held seat has the new duty session-starter, given to the secretary, rigger and lead roles only; NAME validated by regex, so the typed command is fixed), `keep` (one message edited in place) and `delete` (the seat's own messages only, checked by sender); zulip plugin.py's PATCH/DELETE of messages behind them; seats.py `settings --apply` (org edit/delete policy, the owner's to run) and the embassy handshake note (an address, no secret); watch-job.sh `ENDS=1` quieting; duties.toml; the texts as prose | Safe here. No new host; the only new launched command is the fixed `claude` start, and this seat (role downstream, no duties) cannot call it. No settings, cron or service write. |
| 2026-11-11 | v0.1.171 → v0.1.172 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.172 → v0.1.173 | 2 read, credential: scripts/seats.py:419 and skills/onboard/ORG.md:333 (prose saying the handshake note holds no secret) | The v0.1.172 → v0.1.173 diff outside docs/ and tests/ (10 files): seats.py makes an embassy channel with its history open to later members, and PATCHes an older closed one open, so the invited guest reads the handshake note (an address, no secret); watchdog.py `compact` wakes the seat after the /compact it asked for, with its own note (shown, never typed; the typer types only the fixed /compact); ask.py, deskfile.py and plan-watch.py read a desk given as a path; the texts as prose | Safe here. No new host or launched command; the only new server write is a channel's history setting on the organisation's own embassy channel. No settings, cron or service write. |
| 2026-11-11 | v0.1.172 → v0.1.173 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.173 → v0.1.174 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.174 → v0.1.175 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.175 → v0.1.176 | 53 read, all credential words: the new secret-shape detector in drivers/zulip/plugin.py, its telling in watchdog.py, seats.py `delete-message --reason secret`, ledger.py's `secrets` stream, and prose | The v0.1.175 → v0.1.176 diff outside docs/ and tests/ (9 files): plugin.py's SECRET_SHAPES (regexes plus a randomness check) holding a matching message's text back from the seat and its ledger; watchdog.py `secret_posted` (once per message and machine, a direct message to the desk's secretary naming the message, poster and shape, never the secret); seats.py `delete-message` (admin key; dry run by default, `--apply` deletes only a message whose text has a known secret shape, then DMs its poster to rotate it); ledger.py `note()` through the kit's own ledger.sh | Safe here, and protective: the secret's value is never repeated, logged or sent; the only server writes are a DM and the deletion of the leaking message, on the secretary's `--apply`. No new host, settings, cron or service write. |
| 2026-11-11 | v0.1.175 → v0.1.176 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.176 → v0.1.177 | 1 read, credential: rules/AUTOMODE.md:185 (new rule 18) | The v0.1.176 → v0.1.177 diff outside docs/ and tests/ (3 files): rules/AUTOMODE.md rule 18, an auto-mode allow entry (only on admin-key machines) that lets the desk's secretary run `seats.py delete-message ID --reason secret`, then the same with `--apply`, and nothing broader; BASE.md's handoff line restored | Safe here. Text only; it reaches ~/.claude/settings.json only through `automode.py --apply`, which this seat leaves to the person. No new code, host or write. |
| 2026-11-11 | v0.1.176 → v0.1.177 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.177 → v0.1.178 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.178 → v0.1.179 | 6 read: drivers/zulip/teamcheck.py (new); the pool zuliprc globs in onboard.py and watchdog.py; ADOPT.md prose | The v0.1.178 → v0.1.179 diff outside docs/ and tests/ (14 files): teamcheck.py in full (reads the org's users and profile fields with a seat's own key and compares them with a team file; no write); watchdog.py `team_said` at a person's punch-in (a repository with a team file gets one line when it leaves out a person, never a refusal; with no team file, as here, it returns); onboard.py's seating guard (refuses a new seating whose team file leaves people out, `--team-unchecked` passes over it; `git show TIP:team.toml`); seats.py team-sync folded onto teamcheck; watchdog.sh/kit-run.sh wait up to 30 s for a release still copying into the cache | Safe here. Same chat host, read-only with the seat's own key; this seat is never refused by it. No new host, settings, cron or service write. |
| 2026-11-11 | v0.1.178 → v0.1.179 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.179 → v0.1.180 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.180 → v0.1.181 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.181 → v0.1.182 | 1 read: drivers/slurm/watch-jobs.sh (new) | The v0.1.181 → v0.1.182 diff outside docs/ and tests/ (11 files): watch-jobs.sh in full (one watcher for all of a seat's cluster jobs by name prefix: read-only `squeue`, `sacct` and `scontrol show job` for the user's own jobs, state under $XDG_STATE_HOME; no submit, cancel or network); watch-job.sh, facts.sh and slurm.toml.example small changes; the runner/trainer texts as prose | Safe here, and inert: this machine is no cluster site, and no seat here declares a job prefix. No new host, settings, cron or service write. |
| 2026-11-11 | v0.1.181 → v0.1.182 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.182 → v0.1.183 (the 1 hard line accepted by the seat under the person's grant of 2026-11-09) | 1 HARD obfuscation: rules/TRUST.md:62 (prose warning that a pickle runs code as it loads), now listed in scripts/kitgate-accepted.txt; 1 read: bin/trust-check.py (new) | The v0.1.182 → v0.1.183 diff outside docs/ and tests/ (7 files): rules/TRUST.md's new section on the person-given standing `build-for-evaluation` (a runner or trainer seat may build a baseline's repository at a ref the register names, in a scratch folder, after reading its build files; nothing committed or pushed from it); trust-check.py in full (read-only: parses docs/TRUST.md and checks it is committed and clean with `git ls-files`/`status`/`rev-parse`); the runner/trainer texts as prose | Safe here. The hard line is a warning, not code; the checker only reads. This repo keeps a register with no such row, and this seat is neither runner nor trainer. No new host, settings, cron or service write. |
| 2026-11-11 | v0.1.182 → v0.1.183 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.183 → v0.1.184 | 1 read: classes/base/handoff_parts.py (new) | The v0.1.183 → v0.1.184 diff outside docs/ and tests/ (7 files): handoff_parts.py in full (cuts a long handoff into numbered chat messages and joins them on arrival; the id from a message is held to `[a-z0-9][a-z0-9-]{3,79}`, the sender slugged to `[A-Za-z0-9.-]`, at most 40 parts, files only under the seat's own state and handoff folders); hand.sh sending the parts; zulip plugin.py and watchdog.py handing a part to the collector | Safe here. No path escape from a remote id or sender, no new host, command, settings, cron or service write. |
| 2026-11-11 | v0.1.183 → v0.1.184 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-11 | v0.1.184 → v0.1.185 | 5 read, credential: scripts/seats.py usage lines and docstring naming `--rc ZULIPRC` | The v0.1.184 → v0.1.185 diff outside docs/ and tests/ (11 files): seats.py `gaps --person ID --desk DIR [--apply]` (a person who joined is added to every team file the desk holds at that file's join standing, and subscribed to those channels by POST /users/me/subscriptions); nightly.py's secretary job runs team-sync per desk team file, skipping a file with uncommitted edits, and commits each by path in the desk clone (never a repository's own team.toml); ledger.sh, move-to-tag.py, teamcheck.py small changes; the texts as prose | Safe here. Same chat host; the writes are the desk secretary's, in the desk clone and the org's channels, and none touches this repository or this seat. No new host, settings, cron or service write. |
| 2026-11-11 | v0.1.184 → v0.1.185 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.185 → v0.1.186 | 1 read: drivers/github/fix-out.py (new) | The v0.1.185 → v0.1.186 diff outside docs/ and tests/ (5 files): fix-out.py in full (polls an issue through issues.py's read-only `gh api graphql`, fetches a remote's trunk and v* tags into its own refs/fix-out/ namespace, never the clone's branches or tags, and says the release holding the fix through the kit's `watchdog.sh send`); issues.py's new `one()` query; the texts as prose | Safe here. Reads the forge and git only; the one message goes to the asker through the seat's own send. No new host, settings, cron or service write. |
| 2026-11-12 | v0.1.185 → v0.1.186 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.186 → v0.1.187 | 1 read: drivers/host/watch-disk.sh (new) | The v0.1.186 → v0.1.187 diff outside docs/ and tests/ (12 files): watch-disk.sh in full (read-only `df -P -k` and `quota -w` on /, $HOME and named paths, an alarm line under MIN_FREE_PCT; its only write a temp file under $TMPDIR, removed each pass); watchdog.py `holder()` waits up to 15 s for this session's own card during a re-punch instead of refusing; duties.toml gives disk-watch to rigger, secretary and sysadmin and milestones to pm, none to downstream; the role texts as prose | Safe here. Reads only, no network; this seat gains no duty. No new host, settings, cron or service write. |
| 2026-11-12 | v0.1.186 → v0.1.187 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.187 → v0.1.188 | 13 read: bin/org-move.py, drivers/pypi/versions.py and drivers/pypi/watch-pypi.py (new); their urllib calls; pool zuliprc globs | The v0.1.187 → v0.1.188 diff outside docs/ and tests/ (11 files): versions.py in full (GET https://pypi.org/pypi/<name>/json, or PYPI_INDEX, User-Agent naming no one; caches the read under $XDG_STATE_HOME); watch-pypi.py in full (a declared watcher only; on a new version runs the repository's own `[on_publish.*]` commands from its .blueprints.toml, none here); digest.py's `[pypi]` line reads only the cache, never the network; org-move.py read by its phases (a person-started move of a repository's seats to another chat organisation, every phase a dry run until --apply; tickets only encrypted through the embassy; `--flip` commits `[repo] org` in a worktree and pushes, refused while the old org's accounts are active); watch-disk.sh, watchdog.py small changes | Safe here. The one new host is the public package index, read-only; nothing runs unless declared or person-started, and this repo declares no pypi watcher or on_publish hook. No settings, cron or service write. |
| 2026-11-12 | v0.1.187 → v0.1.188 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.188 → v0.1.189 | 2 read: bin/branch-sweep.py and skills/branch-sweep/SKILL.md (new) | The v0.1.188 → v0.1.189 diff outside docs/ and tests/ (6 files): branch-sweep.py read by its git calls (a dry run that sorts local branches as merged, squash-merged, reverted, superseded or unmerged; `--apply` runs `git branch -d` on merged ones only; `--force-unmerged` refuses unless stdin and stdout are a terminal, so only the person can run it; worktree branches left out); the skill, person-invoked only (`disable-model-invocation`), telling the session never to force-delete; levers/kit-tools prose | Safe here, and in line with the person's own rule (`-d` on merged only, never `-D` by a session). No push, no new host, settings, cron or service write. |
| 2026-11-12 | v0.1.188 → v0.1.189 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.189 → v0.1.190 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.190 → v0.1.191 | 5 read, credential words in seatkeys.py and watchdog.py (key renewal) | The v0.1.190 → v0.1.191 diff outside docs/ and tests/ (7 files): seatkeys.py (a seat's gpg encryption subkey now lives 14 days and is renewed 7 days before expiry in the seat's own keyring; the old subkey's secret half deleted, its public half kept; only the public key with the subkey in force is exported; an incoming renewal is read with `--import-options show-only` and imported only when it is the same primary key, never another's or a secret block); watchdog.py `keys_send` (the renewed public key sent to each contact signed and encrypted through the seat's own send, across an embassy when one is known; a refused renewal told to the desk's secretary); plugin.py opening a renewal; prose | Safe here. Only public keys leave the machine; no secret key is exported, no new host, settings, cron or service write. |
| 2026-11-12 | v0.1.190 → v0.1.191 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.191 → v0.1.192 | 4 read, credential words in nightly.py and zulip plugin.py comments | The v0.1.191 → v0.1.192 diff outside docs/ and tests/ (13 files): nightly.py's new `team-sync` job (a declared watcher only: in a private repository with its own team.toml, it carries the desk's new joiners in a fresh worktree via bin/wt.sh, commits by path, and lands through bin/land.sh only with `--land`, the seat's push grant; an empty worktree removed and its branch `-d`); duties.py/duties.toml fallback roles (a duty held acting by lead or tooling where its own role has no present seat); plugin.py blanking OpenPGP armour before the secret-shape check (#442); watch-disk.sh and texts small | Safe here. This seat declares only the zulip and kit watchers, no team-sync job and no team file; no force, no new host, settings, cron or service write. |
| 2026-11-12 | v0.1.191 → v0.1.192 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.192 → v0.1.193 | 8 read, credential: drivers/claude-code/quota.py reading `~/.claude/.credentials.json` | The v0.1.192 → v0.1.193 diff outside docs/ and tests/ (10 files): quota.py's new `account()` (reads the OAuth access token from the credentials file claude-swap swaps, keeps only the first 16 hex of its SHA-256 in the quota cache as a same-or-not marker, never prints or sends it; a cached reading of another account, or one whose window has since reset, is dropped and fetched again, the usage call itself unchanged); watchdog.py `wait-quota` (a seat woken once quota frees, state under the rack); plugin.py, the seats mod and types adding the reading's time to the status; watch-issues.py's protocol regex | Safe here, and it fixes stale quota after a claude-swap switch (the 95% the person called stale on 2026-11-12). The token never leaves the machine and is never written whole; no new host, settings, cron or service write. |
| 2026-11-12 | v0.1.192 → v0.1.193 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-12 | v0.1.193 → v0.1.194 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.194 → v0.1.195 | 3 read: hooks/hooks.json (a new PreToolUse entry), hooks/pace-gate.sh and classes/base/pace.py (new) | The v0.1.194 → v0.1.195 diff outside docs/ and tests/ (14 files): hooks.json adds pace-gate.sh on the client's Workflow tool, `|| true` and no onFailure block, so it fails open; pace-gate.sh read in full (only ever denies a seated session's Workflow call while its watchdog records the pace `small-stop`; reads local cards, writes nothing); pace.py (one pace per organisation, machine and repository read from TOML, its state written atomically under the rack); watchdog.py `pace` and the quota hold following it; quota.py, the seats mod and types; rules/AUTOMODE.md rule 20 (the seat-builder brief change of D193, text only); prose | Safe here. The new hook can only refuse, never run or allow anything; no network, no new host, settings, cron or service write. |
| 2026-11-13 | v0.1.194 → v0.1.195 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.195 → v0.1.196 | 5 read: bin/close-issues.py and bin/item-close.sh (new), item-close.sh's argument lines | The v0.1.195 → v0.1.196 diff outside docs/ and tests/ (14 files): close-issues.py in full (a lead's tool: comments on and closes the issues a release carries with `gh issue comment/close` in the clone's own repository, every check first, each write passed through the kit's forge gate and its .leak_words, `--dry-run` writes nothing); item-close.sh (runs plan-state.sh --check, then close-issues.py, then takes the item out of the plan; its `eval` lines are built only from its own arguments, each single-quoted by `q()`); plan-state.sh, handoff_parts.py, watch-disk.sh, versions.py, plugin.py and watchdog.py small changes | Safe here. Person- or lead-run only, on the kit's own issues, nothing that runs by itself; no new host, settings, cron or service write. |
| 2026-11-13 | v0.1.195 → v0.1.196 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.196 → v0.1.197 | 3 read: classes/desk/intake.py and drivers/claude-code/watch-automode.sh (new), reload.py's `os.setsid()` | The v0.1.196 → v0.1.197 diff outside docs/ and tests/ (40 files): intake.py in full (the desk secretary's tool: removes taken-in inbox files from the desk's own clone and moves the `inbox:pending` label with `gh issue edit` on the desk's repository, `sync --dry-run` writes nothing); watch-automode.sh in full (a watcher every seat now runs, wake off: polls `automode.py --state`, read-only, and keeps one state file under $XDG_STATE_HOME); reload.py (the typer also types into a focused pane once the seat is marked unattended, input line still guarded; logs each Enter to the ledger; `os.setsid()` detaches a forked follower that only reads the plugin's record); automode.py --apply now takes a flock beside settings.json and adds read-only --state; watchdog.py arms the automode watcher and treats scheduled /loop prompts as no one's input; nightly, desk, org-move and transcripts changes | Safe here. No new host, no settings write of its own (automode.py --apply stays the person's), no cron or service; the new writes are a state file, a lock file and ledger lines on this machine. |
| 2026-11-13 | v0.1.196 → v0.1.197 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.197 → v0.1.198 | 1 read: a test fixture in mods/seats/register.test.tsx (a faked process result, not network) | The v0.1.197 → v0.1.198 diff outside docs/ and tests/ (19 files): the new pace position full-stop (pace.py, pace-gate.sh refuses Workflow under it; watchdog.py holds every wake but a person's message and, once, runs reload.py --interrupt); reload.py --interrupt only hands an Escape request to herdr's plugin when the pane is herdr's, the session is working and the input line is empty, else the seat gets a message (no plugin release takes keys yet, so every full stop ends in the message); the seats mod's pace lever runs the fixed `watchdog.py pace --machine POSITION` on a person's press; desk export, stats and trial changes | Safe here. A person-set lever and the kit's own processes only; no new host, settings, cron or service write. |
| 2026-11-13 | v0.1.197 → v0.1.198 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.198 → v0.1.199 | 1 read: classes/desk/epic.py (new) | The v0.1.198 → v0.1.199 diff outside docs/ and tests/ (20 files): epic.py in full (the desk secretary's tool for retro and dream epics: lists, shows, links and unlinks sub-issues and closes an epic with `gh` on the desk's repository, its comment through post.py); automode.py --apply now merges forge owners and leaves a block a newer release wrote (the person's settings still written only by the person's run); move-to-tag.py writes an install record when the only one sits under a renamed clone's old path; ask.py, tick.py, forge.py, export changes for epics | Safe here. Desk and kit tools only; no new host, settings, cron or service write. |
| 2026-11-13 | v0.1.198 → v0.1.199 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.199 → v0.1.200 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-13 | v0.1.200 → v0.1.201 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.201 → v0.1.202 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.202 → v0.1.203 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.203 → v0.1.204 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.204 → v0.1.205 | 3 read: classes/desk/outcomes.py (new), two nightly.py comment lines naming a zuliprc | The v0.1.204 → v0.1.205 diff outside docs/ and tests/ (14 files): outcomes.py (read-only: lists closed desk questions withdrawn with no reason, by asker, reading seat tables through the forge or local paths); nightly.py's new job `outcomes`, the desk secretary's only, sends each asker one chat message a day through the watchdog (the zuliprc lines are comments about which accounts it tries); post.py, deskfile.py, stats.py, forge_gate.py small changes | Safe here. This seat is no desk secretary and runs no nightly job; no new host, settings, cron or service write. |
| 2026-11-14 | v0.1.204 → v0.1.205 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.205 → v0.1.206 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.206 → v0.1.207 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.207 → v0.1.208 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.208 → v0.1.209 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-14 | v0.1.209 → v0.1.210 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-15 | v0.1.210 → v0.1.211 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-15 | v0.1.211 → v0.1.212 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-15 | v0.1.212 → v0.1.213 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.213 → v0.1.214 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.214 → v0.1.215 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.215 → v0.1.216 | 3 read: classes/base/watchdog.py, a guest.zuliprc glob and a urlparse import | The whole watchdog.py diff: `embassies_for` reads only the `[api] site` of this machine's embassy guest.zuliprc files to pick the one embassy serving a contact's chat site (nothing sent, no key read out); `start_in` (start-session, only for a seat with the session-starter or host-starter duty) now runs the seat bootstrap's three `claude plugin` steps at local scope at the calling clone's pin, and writes the client's folder trust through move-checkout.py, after a backup, only where read-only `gh api user` / `user/memberships/orgs` say the clone's origin is the person's own | Safe here. This seat has neither starter duty and never runs start-session; no new host (GitHub through gh only), no service, cron or persistence. |
| 2026-11-16 | v0.1.215 → v0.1.216 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.216 → v0.1.217 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.217 → v0.1.218 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.218 → v0.1.219 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.219 → v0.1.220 | 9 read: bin/org.py (new), classes/plumber/org/seats.toml (new), seatkeys.py, ORG.md's gh collaborators line | The diff outside docs/ and tests/ (10 files): bin/org.py, the organisation's one-command setup (ORG.md phases 0–5), run by the person in their own terminal, a dry run until `--apply`, writing only through the kit's own tools (watchdog.py site, seats.py, new-desk.sh, labels.py, gh) with no URL of its own, counting the pool's zuliprc files by name and never opening the key's file; seats.toml, a seat-table template for a desk; seatkeys.py/watchdog.py: a key renewal is now sent signed and not encrypted, and an unencrypted message opens only when validly signed by a contact and is a renewal, anything else still refused; seats.py `mark --org --except` refuses to mark the owner's account | Safe here. This seat runs no org setup and holds no embassy contacts; no new host, service, cron or persistence. |
| 2026-11-16 | v0.1.219 → v0.1.220 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.220 → v0.1.221 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.221 → v0.1.222 | 2 read: bin/org-move.py's urlparse of the chat's own base URL, and three pre-existing urllib.parse imports | The diff outside docs/ and tests/ (10 files): org-move.py `--flip --id SLUG=ID` (a person's id in the new organisation given by its side, checked against its active people) and a desk's teams/RID.toml taken off where the repository keeps its own; orgconf/org-copy/join/seats.py report an unreadable `org-id` as unknown instead of none; drivers/github/issues.py retries a file delete on a 409 only when the blob is unchanged | Safe here. Organisation-move and setup tools the person runs; this seat runs none. No new host (the chat's own, already used), service, cron or persistence. |
| 2026-11-16 | v0.1.221 → v0.1.222 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.222 → v0.1.223 | 1 read: scripts/seats.py's usage line naming a zuliprc | The diff outside docs/ and tests/ (4 files): seats.py `unarchive CHANNEL [--apply]`, the admin key's GET /streams and PATCH is_archived=false on the organisation's own chat, a dry run unless --apply; org-move.py new-side calls it for a channel an earlier move archived | Safe here. An admin-key command for the secretary and org moves; this seat holds no admin key and runs neither. No new host, service, cron or persistence. |
| 2026-11-16 | v0.1.222 → v0.1.223 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.223 → v0.1.224 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.224 → v0.1.225 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.225 → v0.1.226 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-16 | v0.1.226 → v0.1.227 (held) | 58 read: watchdog.py's machine watchdog (D205): its Unix control socket, cards' tokens, `Server.target()` | The release's point read in full (`start_copy`, `Server.add/stop/seat_main/target`, `pinned_copy`, `serve_join`): every seat on the machine becomes a thread of one process under \$XDG_RUNTIME_DIR, a Unix socket checked by peer uid, each seat's environment passed whole to it; with no user-scope pin it runs the newest clone pin among all its seats' clones and moves there by itself. Nothing new leaves the machine | **Not moved.** Content safe, but adopting would run this seat's watchdog (the chat login, the quota watcher's token) at whatever release another clone pins first, before this gate reads it, which ends docs/TRUST.md's "only this repo's seat moves the pin" for the watchdog. A real fork: put to the person, desk #349, default stay on v0.1.226; kit #521 asks an opt-out. |
| 2026-11-16 | v0.1.226 → v0.1.229 | 59 read: v0.1.227's machine watchdog (the held row above) and v0.1.228's rules/AUTOMODE.md rule 25; v0.1.228 → v0.1.229 clean | v0.1.228 adds auto-mode rule 25 (a seat starts the kit's own contractors on a read-only brief, the fault-finder fetching tla2tools.jar v1.7.4 from its one GitHub release address against a pinned sha256) and org-move.py's check that each seat's notes are committed before a switch. The hold on v0.1.227 is lifted on the person's answer to desk #351 (2026-11-16, in this seat's chat: "reword the register"), the kit's D205 (kit #515) that the watchdog's version is not part of a repository's gate; kit #521 closed as decided | Safe here. The fault-finder runs on this repo only on the person's word. docs/TRUST.md now says the pin no longer governs the seat's watchdog. |
| 2026-11-16 | v0.1.226 → v0.1.229 (moved) | 1 read | the reading in the row above, approved by the person (desk #351) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-17 | v0.1.229 → v0.1.230 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-17 | v0.1.230 → v0.1.231 | 1 read: drivers/watch/shared.py (new) | The diff outside docs/ and tests/ (13 files): shared.py, the machine watchdog's shared watchers (D205 phase 3): per clone one `git ls-remote --symref` and `git fetch -q` of the remote the seat's watcher already reads, and per kit copy one `automode.py --state` read, then each seat's own watch-brief.sh / watch-remote.sh `--step` or watch-automode.sh against that reading, in the seat's own environment; its temporary folders under the watchdog's own runtime folder; plugin.py routes the known watcher commands there, any other runs as before | Safe here. Read-only git and the automode check the seats ran already; no new host, settings write, service, cron or persistence. |
| 2026-11-17 | v0.1.230 → v0.1.231 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-17 | v0.1.231 → v0.1.232 | 3 read: bin/release.py's two `sh -c` test runs, bin/review-batch.py (new) | release.py (the kit's own release command, run in the kit's clone only): the test suite and a failed test re-run alone, niced, each a fixed command or `RELEASE_SUITE`/`RELEASE_RERUN` from the releaser's own environment, the node id shell-quoted; one retry when every failed test passes alone. review-batch.py: read-only `git rev-list`/`diff` cutting the nightly trunk review's batch at 40 files; nightly.py and the trunk-review agent use it | Safe here. Neither runs in this repo: no release, no trunk review here. No new host, service, cron or persistence. |
| 2026-11-17 | v0.1.231 → v0.1.232 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.232 → v0.1.233 | 1 read: the pool's `*.zuliprc` glob in scripts/seats.py and bin/onboard.py | The diff outside docs/ and tests/ (8 files): seats.py `retire-repo REPO [--apply]`, the desk's secretary retiring a finished repository whole (its tickets taken back, its accounts retired or freed through the admin key, its channel archived, its desk records removed in one pushed commit), refused while it has open desk questions or with another organisation's key; a freed spare's stale seat field reset; org-move.py shares those steps; ask.py and the secretary's text small changes | Safe here. An admin-key command of the desk's secretary; this seat holds no admin key and runs none of it. No new host, service, cron or persistence. |
| 2026-11-18 | v0.1.232 → v0.1.233 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.233 → v0.1.234 | 7 hard (foreign secret: seatkeys.py `forget`'s `gpg --delete-keys` and its comments, seats.py's retire-repo contacts step, watchdog.py's usage), 1 read | The diff outside docs/ and tests/ (9 files): `watchdog.py keys forget SEAT CONTACT` deletes a contact's public key from the seat's own keyring and drops it from a pending key renewal; seats.py retire-repo runs it for each seat on this machine holding a retired repository's contact; org-move.py reads a moved-back repository's forge address from the desk's history; herdr's reload typer takes its own scrolled `/reload-plugins` line as its own | Safe here: no key leaves the machine, only public keys of retired contacts are deleted. The seven lines listed in scripts/kitgate-accepted.txt by the seat (standing grant 2026-11-09, desk #197). |
| 2026-11-18 | v0.1.233 → v0.1.234 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.234 → v0.1.235 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.235 → v0.1.236 | 1 read: a docstring in watchdog.py's `own()` naming a message token | The diff outside docs/ and tests/: watchdog.py's own_move retries a failed restart onto the pinned copy up to 3 times, logging why, and `restart` appends its outcome to the seat's log; `read ID` prints a watcher line cut at 500 characters whole from the rack; a short id is looked up among every seat the session holds; a seat whose table cannot be read is unknown (exit 3); BASE.md: worktrees go in the clone's `.worktrees/`, never the scratchpad | Safe here: the flagged line is prose; the restart's Popen was already there, now retried at most 3 times per version. No new host, service, cron or persistence. BASE.md read as its adversary: no concern, this seat makes no worktrees. |
| 2026-11-18 | v0.1.235 → v0.1.236 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.236 → v0.1.237 | 2 read: watchdog.py `still_ours()` comparing the seat card's loop token | The diff outside docs/ and tests/ (watchdog.py, two contractor skills' text): a seat's loop in the machine's watchdog that exits while its session lives is started again with a doubling wait (cap 600 s); a probe that cannot read keeps the loop instead of ending it; the prompt hook names the seat log's last line beside a watchdog found gone; the existing `SEATS_TEST_FAULT` test hook can also exit | Safe here: the token is the card's own loop id, compared locally, never sent. No new host, process, service, cron or persistence. BASE.md and the downstream role unchanged. |
| 2026-11-18 | v0.1.236 → v0.1.237 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.237 → v0.1.238 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.238 → v0.1.239 | 1 read: a comment in nightly.py's new `reach()` on an account's zuliprc | The diff outside docs/ and tests/: nightly.py's new hourly job `silent`, run only by the desk's secretary in the desk's clone, runs the kit's own classes/desk/outcomes.py `--silent` and sends each asker silent on an open desk question for a day one chat message through the existing send; the daily `acting` send refactored into `reach()`; desk protocol, secretary text and template | Safe here: a job of the desk's secretary, which this seat does not run; its sends go through the existing chat client. No new host, service, cron or persistence. BASE.md and the downstream role unchanged. |
| 2026-11-18 | v0.1.238 → v0.1.239 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.239 → v0.1.240 | 2 read: watchdog.py `wake_orphans()`, a card's local socket and its log line | The diff outside docs/ and tests/: the machine's watchdog looks for orphaned seat loops itself every poll and before it ends for want of seats, and a card naming no watchdog (settled 30 s) counts as an orphan; the wake goes through the seat card's existing local Unix socket; outcomes.py resolves the desk's own seats under the label `desk` | Safe here: the socket is the per-user runtime socket already in use, nothing reaches the network. No new host, process, service, cron or persistence. BASE.md and the downstream role unchanged. |
| 2026-11-18 | v0.1.239 → v0.1.240 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.240 → v0.1.241 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.241 → v0.1.242 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.242 → v0.1.243 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.243 → v0.1.244 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.244 → v0.1.245 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.245 → v0.1.246 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-18 | v0.1.246 → v0.1.247 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-19 | v0.1.247 → v0.1.248 | 1 hard (pipe to shell: skills/levers/SKILL.md:28, the row naming the desk's pasted `gh api ... \| sh -s` line), 1 read (the same line) | The diff outside docs/ and tests/: `/seats:seat NAME` takes every seat: where its punch-in refuses (not for a held card), `onboard.py --fallback` runs the take the retired `/seats:take` ran (the desk's bootstrap at its commit, the ticket joined, a pull request for the person to merge), or points a clone with no seats to `/seats:onboard`; seats-export.py and the herdr mod build that one command; watchdog.py and seats.py rename it | Safe here: the row is prose, accepted twice before under `/seats:take`; the take's code path is unchanged, only reached from `/seats:seat` now. This repository declares `downstream`, so its punch-in never reaches the fallback. No new host, service, cron or persistence. The line listed in scripts/kitgate-accepted.txt by the seat (standing grant 2026-11-09, desk #197). BASE.md and the downstream role unchanged. |
| 2026-11-19 | v0.1.247 → v0.1.248 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-19 | v0.1.248 → v0.1.249 | 2 hard (pipe to shell: bin/release.py:134, a regex of process names; skills/levers/SKILL.md:28, the desk's pasted-line row reworded), 7 read (watchdog.py's local socket use, the levers row) | The diff outside docs/ and tests/: the person's `/seat-compact [REPO...]` and `/seat-clear [REPO...]` (the herdr mod's) have watchdog.py tell every seat on the machine, through each card's existing local socket, to stop at a safe point, update its notes and pull its own lever (`/compact`, or `/clear` then `/seats:seat` typed into its own pane by the existing typer); automode.py keeps a record of the forge owners its `--apply` wrote, beside the settings file, to restore one an older copy dropped (the person runs `--apply`, never this seat); release.py, the kit's own release script, measures agent load from /proc and runs its suite under `nice -n 19`; onboard.py's take picks a pull request or overlay by what the repository shows | Safe here: both hard lines are text, no shell; the sockets are the per-user runtime ones already in use; the compact and clear commands are the person's to type. No new host, service, cron or persistence. The two lines listed in scripts/kitgate-accepted.txt by the seat (standing grant 2026-11-09, desk #197). BASE.md and the downstream role unchanged. |
| 2026-11-19 | v0.1.248 → v0.1.249 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-19 | v0.1.249 → v0.1.250 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-19 | v0.1.250 → v0.1.251 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-19 | v0.1.251 → v0.1.252 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-20 | v0.1.252 → v0.1.253 | 2 read: a docstring on tmux's socket path in watchdog.py, and panes.py naming a new pane `tmux:%N:SOCKET` | The diff outside docs/ and tests/: start-session says a seat started only once its card names a live session in the new tab, else the tab's last visible line, read through herdr or tmux's `capture-pane -p` (read only, never typed into); a pane compared across two spellings of tmux's local socket; org-move.py and seats.py small fixes | Safe here: the tmux socket is the user's local one, nothing reaches the network; reading a pane types nothing. No new host, service, cron or persistence. BASE.md and the downstream role unchanged. |
| 2026-11-20 | v0.1.252 → v0.1.253 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-20 | v0.1.253 → v0.1.254 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-20 | v0.1.254 → v0.1.255 | 1 read: classes/desk/post.py's dispatch docstring naming the `gh api` version | The diff outside docs/ and tests/: post.py's workflow dispatch adds `return_run_details: true` to the same GitHub Actions call's body; move-to-tag.py refuses (exit 3) when the client's marketplace record cannot be read; outbound-copy.sh keeps whole the >512 KB files an OUTBOUND_WHOLE list names (the copy stays local, the existing repo-prep path); nightly.py batches the lead's unreleased-fix line; watchdog.py quiets the 5-hour pace line to once an hour | Safe here: the same api.github.com endpoint with one more body field; no new host, service, cron or persistence; nothing new leaves the machine. BASE.md and the downstream role unchanged. |
| 2026-11-20 | v0.1.254 → v0.1.255 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-20 | v0.1.255 → v0.1.256 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-20 | v0.1.256 → v0.1.257 | 2 read: docstrings in drivers/zulip/plugin.py (SECRET_SHAPES, the ledger holding a secret back) and classes/base/forge_gate.py (the desk gate now also denies `gh issue edit` of a question) | The diff outside docs/ and tests/: CLAUDE.md cut to one line per tool; git ls-remote's stderr read apart from stdout in watch-remote.sh and drivers/watch/shared.py, and a malformed listing treated as unknown; nightly.py reports an unknown once per streak; automode.py records the owners an --apply wrote in settings.json.automode-owners (run only on the person's word); small fixes elsewhere | Safe here: the forge gate is tightened, not widened; the ls-remote change reads the same remote; no new host, service, cron or persistence beyond automode's own sidecar file. BASE.md and the downstream role unchanged. |
| 2026-11-20 | v0.1.256 → v0.1.257 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-21 | v0.1.257 → v0.1.258 | 1 read: the new file classes/desk/orders.py | orders.py is read only: it lists the kinds of desk question the person answered alike three times, from the desk's issues through the kit's existing forge.py reader and the desk clone's ORDERS.md, and drafts a proposal body the secretary files through ask.py. Elsewhere: nightly.py runs it as the secretary's job; land.sh, review-batch.py and drivers/watch/shared.py small fixes (a late-killed step no longer ends a shared watcher) | Safe here: no write, no new host (GitHub via the existing gh reader), no cron, service or persistence; it runs only for a desk's secretary, which this repo has not. BASE.md and the downstream role unchanged. |
| 2026-11-21 | v0.1.257 → v0.1.258 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.258 → v0.1.259 | 1 hard, 41 read: new host learn.chatgpt.com; the Codex driver (drivers/codex/native.py, seat.py, resolve.py, hooks.json, .codex-plugin, .agents marketplace), drivers/claude-code/ask-predecessor.py, release.py's rerun shell string, laurels.py, restated.py, presence.py, retro-metrics.py, the script-bit pre-commit hook, rules/CODEX_AUTOREVIEW.md and NIGHT.md, a base line on unlocked worktrees | The host appears only as documentation links (rules/CODEX_AUTOREVIEW.md, docs/CODEX_CLI.md); no code fetches it. native.py speaks WebSocket to Codex's own local daemon over an AF_UNIX socket under $CODEX_HOME, reads thread state and rate limits, queues wakes only to a recorded loaded thread; its record files are 0600 and its token is a random uuid. seat.py and hooks.json are Codex-client hooks (inactive here: no Codex plugin installed), running the existing watchdog and forge gate. ask-predecessor.py runs `claude --fork-session --resume` read-only (Read/Grep/Glob only, dontAsk, no MCP, hooks off, no persistence, never --dangerously-skip-permissions), the asker's identity env stripped, only when a seat runs it. release.py's `sh -c` joins RELEASE_RERUN (the kit's own release env) with a shlex-quoted test node. The other new scripts call git or local tools by argv list, no network. The auto-review rule is a draft policy that grants nothing until the person applies it | Safe here: no new fetched host, no persistence, no credential read beyond the kit's own state. Hard line accepted under the standing grant of 2026-11-09 and listed in scripts/kitgate-accepted.txt. |
| 2026-11-22 | v0.1.258 → v0.1.259 (moved) | 1 hard, 41 read | the reading in the row above, the hard line accepted under the standing grant of 2026-11-09 | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.258 → v0.1.259 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.259 → v0.1.260 | 3 read: the new files classes/base/feedback.py, drivers/claude-code/context.py, skills/feedback/SKILL.md | feedback.py appends a seat's feedback to a local JSON-lines store under $XDG_STATE_HOME, under a lock, and reads it back; no network. context.py records the context fill the plugin's mod hands it (a percentage and window) in the runtime dir; the mod starts it by `sh -c` with the session id and numbers as positional arguments, never interpolated; the watchdog turns band crossings into an `info:` line. Elsewhere: org-move.py and seats.py fixes, the first-mate role text, a base section on a seat's own reset and a diary file | Safe here: no new host, no persistence, no credential read. |
| 2026-11-22 | v0.1.259 → v0.1.260 (moved) | 3 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.259 → v0.1.260 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.260 → v0.1.261 | 3 read: the new files bin/doc-edit.sh and rules/BUILD.md, and BUILD.md:29's credential word | doc-edit.sh lands one replace-once edit through the kit's existing wt.sh and land.sh against origin (the clone's own forge), refusing if the file moved between reads; it reads no secret and starts no network beyond git fetch/push to origin. BUILD.md is a build brief whose line 29 forbids reading secrets files, --no-verify and stash drops. Elsewhere: land.sh --peer lands another seat's pushed branch (a remote branch delete only with --delete-remote, leased on the merged tip, else a paste line for the person), plan-state and plan-watch changes, a `watchdog.sh forward` command, a base line naming it | Safe here: no new host, no persistence, no credential read; nothing this seat runs deletes anything. |
| 2026-11-22 | v0.1.260 → v0.1.261 (moved) | 3 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.260 → v0.1.261 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.261 → v0.1.262 | 1 read: the new file bin/state-counts.py | state-counts.py runs `git fetch --tags origin` and counts the version, plan states and release tags from origin's trunk, printing three lines; no forge call, no write. Elsewhere: the digest's `[forge]` line reads the GraphQL budget through the existing desk forge reader (classes/desk/forge.py, GitHub's rate_limit, already audited), only on a machine that keeps a reading | Safe here: no new host, no persistence, no credential read. |
| 2026-11-22 | v0.1.261 → v0.1.262 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.261 → v0.1.262 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.262 → v0.1.263 | 1 read: the new file rules/RETIRING.md | RETIRING.md is a handover checklist for a retiring seat, by hand, in its notes and direct messages; no code. Elsewhere: the desk's forge.py notes issues this machine posted on (a local JSON file under a lock); herdr/reload.py may type one fixed farewell line before `/exit` at a retire, its path checked against a strict pattern under the state folder, `..` refused and the file required to exist, so no free text is typed; AUTOMODE rule 14's text says so (taken in only by `automode.py --apply`, not run here); sysadmin and presenter role texts, plan-watch counting nights | Safe here: no new host, no persistence, no credential read. |
| 2026-11-22 | v0.1.262 → v0.1.263 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-22 | v0.1.262 → v0.1.263 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-23 | v0.1.263 → v0.1.264 | 90 read: the new drivers/beads/beads.py and rules.sql (plan items as bd cards on a private dolt server), drivers/dolt/metrics.py (the ledger's metrics to a public dolt database), nightly.py's new `metrics` job, fourteen Codex skill manifests | beads.py reaches a private dolt server named in the machine's credentials file (default under the state folder) by a TCP probe and `bd`/`dolt` with the password in the environment, never printed; a server address is scrubbed from every message; card writes are compare-and-set. metrics.py publishes the machine's ledger lines to a public dolt remote named only in the machine's config (`metrics-remote`, written by a hand-run `setup`): every identifier is a keyed HMAC stand-in whose map stays on the private side, every free text encrypted (HMAC-CTR, encrypt-then-MAC), the whole dump run through the clone's leak list first (no list, nothing published), dolt's usage reports required off. nightly.py runs it only for a seat whose table declares a nightly watcher with the job `metrics`; this clone's table declares none, so no seat here publishes. On this machine `metrics-remote` already exists (2026-11-22, the person's setup), so another repository's seat may publish the shared ledger, this seat's lines included, as stand-ins and ciphertext | Safe here: no new host in code, no persistence added here, the private credentials never leave; the public side carries no plain identifier or text. The person's own design (the maintainer, 2026-11-22: "one private ... one public, unlimited"). |
| 2026-11-23 | v0.1.263 → v0.1.264 (moved) | 90 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-23 | v0.1.263 → v0.1.264 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-23 | v0.1.264 → v0.1.265 | 10 read: drivers/codex/native.py and seat.py (six `token` hits), watchdog.py's wake fallback and EDGES.md:203 (`socket`), the new scripts/wake-cost.py | Every `token` is a wake attempt's own uuid4, not a credential. The new wake pointer (L185) types one fixed line, `[seat wake] N new: ...`, N digits only, into the seat's own pane through the existing herdr typer (drivers/herdr/reload.py); it never carries a sender or message text, never types a focused pane, and backspaces itself out if stopped before Enter; BASE.md adds that this exact line grants nothing. Its fallback posts the pending listing into the session's own local socket, as before. wake-cost.py counts transcript records and runs `git -C` locally, printing numbers only. Also: Zulip forwards from a sibling instance checked by account name (L187), UTF-8 writes (#599), Codex `--serial-agent` for one contractor under the pace gate, presence.py for nightly retros on steered days. No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-23 | v0.1.264 → v0.1.265 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-23 | v0.1.265 → v0.1.266 | 5 read: the new rules/AUDIT.md (its `credential` hit is a rule never to read a secrets file), classes/base/reported.py, drivers/codex/transcripts.py, skills/persona/SKILL.md | AUDIT.md is an adversary auditor's procedure: scratch copies only, never the real seats, ledger, config or servers, never commit or push. reported.py counts, at a turn's end, a report written after a wake that needed nothing (L190); it writes one mark file beside the session's card and refuses, trims or delays nothing. transcripts.py reads a local Codex rollout for a retro, with no daemon contact and no network. persona is an optional skill: a `## Persona` section in the seat's own notes, its avatar through the existing `watchdog.sh avatar`. watchdog.py's additions are a wake filter for release and trunk-news lines, counted; no new subprocess, host or secret. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-23 | v0.1.265 → v0.1.266 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-24 | v0.1.266 → v0.1.267 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-24 | v0.1.267 → v0.1.268 | 1 read: the new classes/base/chatleak.py | chatleak.py runs bin/leak-check.sh (new `--classes` mode: prints only which pattern line or `abs-path` matched, never the text) and the absolute-path check over a seat's chat post after the server took it, in a temp folder it removes, with a 20 s limit that stops the whole process group; it refuses nothing and records `clean`, `matched` or `unknown` in a local ledger stream `leaks`, never the text or pattern. drivers/dolt/metrics.py now leaves that stream out of the public metrics publish. onboard.py: git or desk read failures said as unknown. No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-24 | v0.1.267 → v0.1.268 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-24 | v0.1.268 → v0.1.269 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-24 | v0.1.269 → v0.1.270 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-25 | v0.1.270 → v0.1.277 | 1 hard + 31 read: drivers/claude-code/bootstrap.sh.in:66 (persistence); the new bin/duty-run.py, drivers/claude-code/headless.py, drivers/codex/headless.py, classes/liaison/upstream-context.py, classes/base/rackcards.py, classes/base/CODEX.md; `token` hits in beads.py, wake-corpus.py, transcripts.py, native.py; AUTOMODE.md rules 26-27 | The hard line reads, never writes, the managed and user settings files to find a machine-wide pin of the kit's marketplace, and the bootstrap then follows it instead of adding its own (#622); accepted in scripts/kitgate-accepted.txt (standing grant 2026-11-09). duty-run.py starts a headless model only for a watcher whose table declares `duty` (this clone declares none): `claude -p` with no tools, safe mode, restricted settings, no MCP, dontAsk, no transcript; `codex exec` with the shell and web search off, read-only sandbox. upstream-context.py reads local clones and the client's changelog. The `token` hits are claim and wake uuids. drivers/leaves/relay.sh now runs the relay skills at `kit-pass`, a forward-only branch of the person's own fork fetched over ssh in batch mode, floored at a pinned commit (the person, 2026-11-24); it runs only for a leaf or consensus review, and its code is the person's fork, not the kit's tag. AUTOMODE rules 26-27 are text for the person's auto-mode list, which this seat never applies unasked. No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-11-09. |
| 2026-11-25 | v0.1.270 → v0.1.277 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-25 | v0.1.277 → v0.1.278 | 1 hard + 4 read: rules/AUTOMODE.md:225 (rule 28: foreign secret, credential, network); the new bin/parity.py | Rule 28 is text for the person's auto-mode list: a seat may ssh/scp to the person's own hosts through an alias their sysadmin seat set up with a dedicated low-privilege key, `IdentitiesOnly`, no agent, no sudo. It names a key file and holds no secret; this seat never applies auto-mode rules unasked. Accepted in scripts/kitgate-accepted.txt (standing grant 2026-11-09). parity.py classifies paths as Claude, Codex, shared or neutral and lists commits missing a `Parity:` line, by local `git` only. Also: the downstream role split, the fork's duties moved to a new role `fork-keeper` (D223, kit f7a8be4a). No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-11-09. |
| 2026-11-25 | v0.1.277 → v0.1.278 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-11-09) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.278 → v0.1.279 | first hard (a moved tag), then clean | The fetch was refused on `claude-latest` and `codex-latest`. Both are markers that the kit's `bin/release.py` moves forward at each release by design (kit D221). Each had moved from the v0.1.278 commit to the v0.1.279 commit, and the tag objects for v0.1.278 and v0.1.279 match the kit's remote. `scripts/kitgate.py` now fetches every other tag as before, so any other moved tag still stops the gate. It takes in a marker only when the marker moved forward to a commit that a `v*` tag names; a marker moved backward, sideways or to a commit no release names stops the gate (tests/test_kitgate.py). The regate is clean. | Safe. Moved on a clean gate. |
| 2026-11-26 | v0.1.278 → v0.1.279 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.279 → v0.1.280 | 29 read: network (AF_UNIX `socket` connects to herdr-core's socket in drivers/herdr/panes.py and reload.py), credential (a docstring naming CLAUDE_CODE_USE_BEDROCK and an OAuth token as config kept), shell string (`sh -c` in panes.py), new file classes/base/muxpane.py | Support for herdr-core's `hc` as a fourth local multiplexer (RM74). Before each call to `hc`, the code tests whether a core listens on a local Unix socket, and the socket path is taken from `$HC_TERMINAL_SOCKET`. A new terminal is started by `hc run ... sh -c`, with herdr, tmux and parent-session variables unset first. The reload typer sends only its fixed texts, through `hc send`. muxpane.py reads `/proc/<pid>/stat` and `/proc/<pid>/comm` and the environment to name the pane. relay.sh now lists the user's new entries in the shared temporary folder and removes none of them. The watchdog squashes messages per conversation (#646). move-to-tag.py takes its pane rule from muxpane.py. No new host, no network beyond local Unix sockets, no secret read, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.279 → v0.1.280 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.280 → v0.1.281 (moved) | 0 clean | nothing on the watched paths | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.281 → v0.1.282 | 1 read: network (rules/AUTOMODE.md:166, auto-mode rule 14's text) | Rules 14 and 21 now name herdr-core's terminals: the reload typer may type its same fixed texts through `hc send --if idle`, after the read-only `hc get` and `hc read`, only into the seat's own terminal, and a starter seat may open a visible terminal by `hc run --bg --no-parent` on the core already listening, Claude Code only, in a folder the client already trusts. This seat does not run `automode.py --apply`, so the text changes nothing here. Also read: reload.py treats the client's suggested prompt as an empty line while the seat is unattended (never for a wake); watch-remote.sh fast-forwards under the clone's sync lock; automode.py refuses an owners record it cannot read instead of rewriting it; forge_gate.py stops judging a release asset's lines that a pushed tag already serves (publishing only, which this seat never does); seats.py reads the team file by the repo id. No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.281 → v0.1.282 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.282 → v0.1.283 | 15 read: network and credential in drivers/beads/beads.py (getaddrinfo, a connectionless UDP route check, the TCP probe), credential wording in classes/lead/plan-watch.py, auto-mode rule 14's text | The beads driver (the kit's plan cards on its dolt server; this repo keeps no cards) now connects less often. It reads in one pooled SELECT, and it probes the server only after a bd call failed. It counts its calls an hour into the ledger. Where the server's name has an IPv6 address with no route, it dials IPv4, and hands the address to bd only with TLS off. Usage reporting is shut off further (OTEL_SDK_DISABLED, BEADS_DOLT_AUTO_START=0, dolt's root in the workspace with metrics.disabled; ~/.dolt never written). It refuses `bd init` without --skip-hooks, `bd hooks install` and `bd config apply`, which would write git hooks. plan-watch.py caches the card read for 15 minutes unless the plan files move. Rule 14 now treats the client's suggested prompt as an empty line while the seat is unattended (never for a wake), and the AUTOMODE.md preamble documents the owners record. No new host beyond the server the credentials already name, no secret read beyond them, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.282 → v0.1.283 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.283 → v0.1.284 | 1 read: new file classes/base/claudebatch.py | The daily Claude batch (L205, the person 2026-11-25): Claude Code seats on a machine move to a newer kit at most once a day, unless the release commit carries `Claude-seats: now`. The clock is a machine-local state file, `$XDG_STATE_HOME/agent-seat-blueprints/claude-batch.json`, with its own said-file beside it, and nothing tracked. move-to-tag.py and release.py gate on it. The machine's watchdog follows only a copy that the batch took or is due for; otherwise it starts the batch's own cached copy, and it tells each held seat the command that resumes the move. Also read: the watchdog's changed lines, which add no network beyond its existing Zulip delivery. The desk scripts add the reopening of a Your-move line. No new host, no secret read, nothing published. One effect here: this seat moves its own pin with kittrack.py, so the machine's watchdog may run the batch's copy for up to a day after a pin move. kittrack's installed-copy check covers the client's install record, not that. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.283 → v0.1.284 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.284 → v0.1.285 | 5 read: network and credential in classes/base/watchdog.py (wake_legacy), credential wording in skills/onboard/START.md | The machine's watchdog now finds a seat whose own watchdog, from before the machine's one watchdog (D205), still runs. It wakes that seat once through the seat's existing local socket with the two commands that move it, and stops nothing. The metrics driver can start an empty public dolt database from this machine: an init under the driver's own author in UTC, then a remote add and a first push, to the remote it already used. The onboarding text, and the fork-keeper role, now say the forge login needs the `workflow` scope to push an upstream's workflow files. This machine's token has it; checked by `gh auth status` 2026-11-26. The base says a step handed to the person carries its exact action. Rules 1 and 8 changed wording on the desk only. No new host, no secret read, nothing published by this seat. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.284 → v0.1.285 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-26 | v0.1.285 → v0.1.286 | 4 read: new files classes/base/dailyowed.py and overlong.py; auto-mode rules 26 and 30 | dailyowed.py counts this seat's Seat-trailer commits on origin's trunk with a local `git log`, to remind it of the daily line. overlong.py tells a seat once a day when a reply to the person ran over eight lines; it keeps only the line count, never the text. Both keep a small per-seat JSON under `$XDG_STATE_HOME/agent-seat-blueprints/`, with no network and no secret. New rule 30 lets a seat delegate to Codex (`codex exec`, a profile that keeps secret files from the run, a read-only or workspace-write sandbox, the seat's own clone). It excludes a repository whose own rules keep its files from outside models, and this repo opts out (`outside = "never"`, docs/TRUST.md), so this seat delegates nothing to Codex. Rule 26 points Codex delegation to rule 30. A wake let go with no tool call now counts as needed-nothing by itself. The watchdog's diff adds no host. Nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-26 | v0.1.285 → v0.1.286 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-27 | v0.1.286 → v0.1.287 | 14 read: new files bin/cleanup.py, classes/base/pointers.py, rules/SWARM.md, drivers/codex/skills/cleanup/agents/openai.yaml; `token` and `credential` wording in pointers.py, plan-watch.py and beads.py | cleanup.py lists the local branches, unlocked worktrees under `.worktrees/` and quiet scratch folders that can go. Only the person starts a run (`/seats-cleanup WORD` or a terminal), never a seat. It deletes only entries still unchanged since the list the person saw: a local `git branch --delete --force` of a merged-class branch (protected names and tags excepted), `git worktree remove --force`, or an rmtree anchored to its folder. It never pushes, and it never deletes a remote branch. This seat never runs it (the person's rule: never `-D`). pointers.py's "token" is a `[card ID @sha12]` digest of a plan card's state, with no secret; it reads quota records locally and cards through the beads driver. SWARM.md is guidance for several seats in one channel. The yaml sets `allow_implicit_invocation: false`. land.sh runs the tests that name a changed path. The watch plugin keeps trailing pointers whole when it cuts a line. Rule 23 lets a seat make a throwaway, test-prefixed account on a rehearsal instance its priming names; this seat's priming names none. No new host, no secret read, nothing published. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-27 | v0.1.286 → v0.1.287 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-27 | v0.1.287 → v0.1.288 | 4 read: drivers/zulip/plugin.py:1444, :1370, :113 (`http.client` import and its exceptions), drivers/pypi/versions.py:46 (unchanged import, flagged by pattern), drivers/herdr/panes.py:250 (`hc` run with any status) | The Zulip driver now reads a thread's last 50 messages and one message by id from the same chat server it already talks to, to carry one seat's first answer to a person's post to the other seats it reached (L213); herdr's `hc get` reports a gone pane, used with a new local open-tab record under the state home so a second seat start points at the tab already open (#680). Also: land.sh keeps an option's value with its option when picking test files, outbound-copy refuses a folder as OUTBOUND_WHOLE, nightly reads the release hold inside its try, quota pace kept across an unknown streak; rules: audits run under timeouts and never force anything. No new host, no new write outside the state home, no push or delete of git refs. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-27 | v0.1.287 → v0.1.288 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-27 | v0.1.288 → v0.1.289 | 6 read: drivers/claude-code/context.py:23, :43, :154 and classes/base/pointers.py:30 (the word "token" as context-size counts, no credential), drivers/zulip/plugin.py:1997 (`http.client` exception on a message read from the same chat server), new bin/merge-plan.py (a git merge driver for the kit's own plan files: `git merge-file` on temp copies, writes only the file git hands it) | A context notice at 170,000 tokens; a seat can mute one chat thread for up to seven days; forward by inbox id quotes the original; plan-state.sh can add an item; land.sh runs a repository's `[land] always` tests under nice 19. The merge driver is configured only in the kit's own repository (its CLAUDE.md setup line and .gitattributes); this repo installs neither. No new host, no push, no delete of git refs. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-27 | v0.1.288 → v0.1.289 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-27 | v0.1.289 → v0.1.290 | 2 read: drivers/zulip/plugin.py:921 (a failed read of the repository's pace posts from the same chat server is logged, not fatal), new classes/base/hibernation.py (a repository-wide hibernate position: local marker files and ledger notices under the state home, no network, no git) | A repository can hibernate: pace-gate denies every tool call and the reload typer stops until the lift; move-to-tag refuses a pin move while hibernating. Codex-only, noted for the record: a new `watchdog.sh codex-trust` and auto-mode rule 31 mark the kit's own Codex hooks trusted through Codex's app server after a move, a dated config backup made first, at the person's request (kit #693); Codex hooks fall back to a kept copy of a removed plugin folder. This repo runs Claude Code only and sends nothing to outside models (`outside = "never"`), so neither runs here. No new host, no push, no delete of git refs. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-27 | v0.1.289 → v0.1.290 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |
| 2026-11-27 | v0.1.290 → v0.1.291 | 2 read: rules/AUTOMODE.md:224 (rule 27's niceness widened from 19 to 15–19, the person's word 2026-11-27; "key" in its exclusion list), drivers/codex/seat.py:107 (the watchdog's own token field read from a seat card, Codex only) | Test runs move to nice 18 (the machine's guard accepts 15–19); the question gate's seat-card check moved into classes/base/rackcards.py and now denies the dialog when a card is unreadable instead of allowing it; claim.sh no longer reads a notes-only commit as an issue's fix; Codex stop and interrupt bookkeeping. No new host, no push, no delete of git refs. | Safe. Moved under the standing grant 2026-10-21. |
| 2026-11-27 | v0.1.290 → v0.1.291 (moved) | 1 read | the reading in the row above, approved by the person (standing grant 2026-10-21) | Moved by `scripts/kittrack.py move`, per the standing adoption. Installed copy == tag. |