# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-10-08, extended 2026-10-10, 2026-10-16, 2026-11-04, 2026-11-07 and 2026-11-09
**Versions audited:** `0.26.0`; `0.27.0`, `0.27.1` and `0.27.2`; `0.28.0` and
`0.29.0`; `0.30.0` and `1.0.0` (the last adopted, see
[below](#also-audited-0300-and-100-and-the-fork-merge-41cc1fb));
the fork's `0.27.0b1` at commits `33bb12f` and `5a2211f`, its `0.28.0b1` at
`70dde18`, its `0.29.0` at `babc945`, and its `1.0.0` at `41cc1fb` (git installs, which
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

### To run exactly the audited version

```bash
uv tool install 'claude-swap==1.0.0'       # current stable — verified clean
# or the audited fork commit (pin the full sha; a branch name moves):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@41cc1fb55d0c8718052781b5c011a46dc7e94965'
# or follow the fork's audited tag (what `cswap upgrade` runs):
uv tool install --force --reinstall 'claude-swap @ git+https://github.com/winternewt/claude-swap.git@audited'
```

Any commit after `41cc1fb` that touches `src/` or `pyproject.toml` is
**unaudited**. The `audited` tag points at the commit that records this
sentence. Its code is `41cc1fb`'s: the commits after it touch only this file
and `docs/`.

**Marker history** (the old commit is recorded here before each move, as the
seat's grant requires):

| Date | `audited` moved from | to | Code audited |
|---|---|---|---|
| 2026-10-16 | (new) | `d138f8d` | `70dde18` |
| 2026-10-16 | `d138f8d` | `a2b2f43` | `59d9ffb` |
| 2026-11-04 | `a2b2f43` | `57d54c1` | `babc945` |
| 2026-11-09 | `57d54c1` | the commit adding this row | `41cc1fb` |

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