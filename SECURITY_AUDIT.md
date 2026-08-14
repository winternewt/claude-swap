# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-08-14
**Version audited:** `0.25.0` (current stable — what a plain install gets)
**Previous audit:** 2026-06-25, versions `0.14.0` / `0.15.0b1`
**Auditor:** independent review on the `winternewt` fork
**Method:** re-audit of the `0.15.0b1 → 0.25.0` delta (323 commits, +17,845 /
−1,156 lines across `src/`), plus byte-for-byte verification of the published
PyPI artifacts against the git source.

---

## Verdict: ✅ Clean

No phone-home, no data exfiltration, no backdoor. Safe to expose Claude Code
OAuth tokens to `0.25.0`.

The headline of this re-audit: **the package roughly tripled in size, and the
network and execution surface did not grow with it.** 20 new modules — an
auto-switch engine, a Textual TUI, a macOS menu-bar app, a usage store — added
exactly *one* new endpoint, on a host that was already trusted. `switcher.py`
alone gained 5,402 lines containing zero network, subprocess, or eval
constructs.

**One thing genuinely changed and the previous audit's text is now wrong on
it:** that report said the tool "runs synchronously and exits, so nothing
lingers." That is no longer true — see [Background execution](#background-execution-this-is-new)
below. The behavior is legitimate and user-initiated, but it is new, and it
polls Anthropic on a timer.

---

## Network surface — complete, 4 endpoints, all hardcoded literals

| Endpoint | Method | What is sent | Source |
|---|---|---|---|
| `https://platform.claude.com/v1/oauth/token` | POST | `refresh_token` + Claude Code's public `client_id` — standard OAuth refresh | `oauth.py:18,143` |
| `https://api.anthropic.com/api/oauth/usage` | GET | `Authorization: Bearer <access_token>` — reads usage % | `oauth.py:366` |
| `https://api.anthropic.com/api/oauth/profile` | GET | `Authorization: Bearer <access_token>` — **new since last audit** | `oauth.py:249` |
| `https://pypi.org/pypi/claude-swap/json` | GET | **nothing** — anonymous, reads only the version field | `update_check.py:16` |

- All four URLs are **hardcoded string constants**, not built from config or
  environment, so they cannot be silently redirected.
- Only **two modules in the entire package** perform network I/O: `oauth.py`
  and `update_check.py`. Both use `urllib.request` only. A full-tree grep for
  `socket`, `requests`, `httpx`, `aiohttp`, `smtplib`, `ftplib`, and
  `http.client` returns nothing anywhere else.
- Credentials go **only** to Anthropic's two own domains. No `os.environ` value
  feeds any request body, header, or URL.

### The new `/oauth/profile` endpoint

`fetch_oauth_profile()` resolves "whose token is this" — it sends the Bearer
token and nothing else, and reads back `{uuid, email, organizationUuid}`. It
sends no more than the already-audited usage endpoint does, to the same host,
and it is strictly advisory: every failure path returns `None` and the caller
proceeds with pre-existing behavior. No new trust boundary is crossed.

### `truststore` (new dependency)

`cli.py:_use_native_tls()` calls the stock `truststore.inject_into_ssl()`,
delegating certificate verification to the OS-native verifier (SChannel /
SecureTransport). This **strengthens** TLS verification rather than relaxing
it — it exists because OpenSSL's flat Windows cert store can let a stale
expired intermediate shadow a valid chain. On any exception it falls back to
stdlib `ssl`. No `verify_mode`, `CERT_NONE`, `check_hostname`, or custom CA
bundle appears anywhere in the tree.

## Background execution (this is new)

The previous audit's "no background threads, timers, or lingering processes"
claim no longer holds. What actually exists now:

- **`cswap auto`** (`autoswitch.py`, 2,364 lines) — a usage-polling engine that
  switches accounts before they hit rate limits. `--once` ticks and exits;
  `--loop` runs a foreground loop that exits cleanly on SIGTERM
  (`cli.py:711`). Its network activity is exactly the usage/refresh endpoints
  above, on a backoff-governed schedule (`poll_policy.py`).
- **Menu-bar app** (`menubar.py`, macOS, `menubar` extra) — `rumps.Timer`
  refresh ticks plus `daemon=True` worker threads.
- **Helper threads** — `claude_locks.py` lock-file toucher, TUI worker threads.
  All `daemon=True`, all in-process.

**Crucially, none of this installs persistence.** There is no LaunchAgent, no
systemd unit, no cron/`schtasks` entry, no login item — a full-tree grep for
`launchctl`, `LaunchAgents`, `systemctl`, `crontab`, `schtasks`, `RunAtLoad`,
and `KeepAlive` finds only documentation comments. Every long-running mode is
started explicitly by the user in the foreground and dies with its process. The
one `.plist` written is a two-key `Info.plist` (`CFBundleIdentifier`,
`CFBundleName`) placed beside the Python interpreter so macOS will show rumps
notifications — not a launch agent, and not in `~/Library/LaunchAgents`.

The honest summary is: *nothing runs that you did not start, but what you start
may now legitimately run for hours and poll Anthropic while it does.*

## Process / execution surface

- `subprocess` appears in only four modules: `macos_keychain.py` (the system
  `security` CLI), `update_check.py` (`uv`/`pipx upgrade`), `session.py`
  (launching `claude`), and `menubar.py` (one `["open", "-R", path]` to reveal
  a file in Finder). All are hardcoded argument arrays.
- **No `shell=True` anywhere.** No `eval`, `exec`, `os.system`, `os.popen`,
  `pickle`, `marshal`, or `__import__` of attacker-controllable input.
- The published wheel contains **no binaries, no build hooks, and no
  `setup.py`** — 39 `.py` files, one `.tcss` stylesheet, and metadata. Entry
  points are the two expected console scripts (`cswap`, `claude-swap` →
  `cli:main`).

## Local state — no tokens on disk beyond the credential store

`usage_store.py` (new, 1,221 lines) persists per-account usage measurements and
fetch/backoff state to `cache/usage.json`. It stores **no tokens**: account
identity is carried as `credential_fingerprint()`, a
`sha256:`-prefixed SHA-256 of the refresh token (`oauth.py:43`), never the
token itself. Writes go through `atomic_write_json()`, which inherits the
backup directory's `0600`/`0700` modes.

## Things that continue to raise confidence

- **`/usr/bin/security` is still pinned by absolute path**; secrets pass via
  stdin, never `argv`.
- **Auth env scrubbing expanded** from the previous audit — now five variables
  (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, and
  two file-descriptor variants) are stripped before `claude` launches
  (`session.py:193`).
- **Export still strips machine-identity fields** and never auto-uploads;
  import still has explicit path-traversal guards.
- `base64` remains confined to local `.enc` credential backups —
  encode-to-disk / decode-from-disk, not obfuscation.
- No custom `keyring` backend is registered.
- Deliberate discipline against network-under-lock, documented and enforced at
  several call sites ("Must not be called while any credential/config lock is
  held").

## Dependencies — this is the real expansion

The previous audit could say "one runtime dependency." That is no longer true.

| Dependency | Scope | Notes |
|---|---|---|
| `textual >=8.2.8,<9` | all platforms | TUI framework; pulls `rich`, `markdown-it-py`, `mdit-py-plugins`, `mdurl`, `linkify-it-py`, `uc-micro-py`, `pygments`, `platformdirs`, `typing-extensions` |
| `truststore >=0.10.4` | all platforms | no transitive deps |
| `keyring >=25.0.0` | **Windows only** | *narrowed* — was all-platforms, now only for the legacy migration |
| `rumps >=0.4.0` | `menubar` extra, macOS | pulls `pyobjc-framework-cocoa`, `pyobjc-core` |

Net: ~10 transitive packages on Linux where there were previously ~6, all of
them mainstream, widely-audited projects with no typosquat lookalikes. Narrowing
`keyring` to Windows is a genuine reduction in default attack surface for
Linux/macOS users. Still, **the dependency count is now the largest untrusted
input to this package** — larger than its own code, from a supply-chain
perspective.

---

## Supply-chain verification (published artifact == source)

The audited GitHub source is not automatically what `uv tool install` pulls —
the PyPI package is published by `realiti4`, and this is the `winternewt` fork.

### `0.25.0` — published == fork source, byte-for-byte

All **40 files** (39 `.py` + `tui/cswap.tcss`) in the published wheel are
SHA256-identical to `src/claude_swap/` at commit `9f62506`, the 0.25.0 version
bump (PyPI upload date 2026-08-11 matches the commit date). The **sdist and
wheel are also identical to each other**, so both install paths deliver the
same code.

```
wheel  sha256: c8854305e4e6165f3112fe187582594d85ba4e1f198ccbe5a0cf6d76b414aaba
sdist  sha256: e665dbd7249f1211a5bc6df384c10965d78fd950b2cde305e1af93a73c8648d0
```

Both downloads were re-hashed and matched PyPI's own published digests.

> **Note on running `scripts/redflag.sh` against a dirty tree:** the script's
> `--repo` check compares the published artifact against the *working tree*. The
> repo currently sits at the unreleased `0.26.0b1`, so that check reports
> `DIFFERS: credentials.py`. That is an artifact of comparing against unreleased
> work, not a supply-chain problem — against the actual 0.25.0 release commit,
> everything matches.

### To run exactly the audited version

```bash
uv tool install 'claude-swap==0.25.0'      # current stable — verified clean
```

### Unaudited: `0.26.0b1`

The working tree is at `0.26.0b1`, which is **not published to PyPI** and is
**not covered by this audit**. Its only source delta vs 0.25.0 is
`credentials.py`.

---

## Limits of this audit

- Verification is **per-version**. Any future release is unaudited until
  re-checked — the maintainer can publish a new artifact at any time.
- **Method disclosure:** at +17,845 lines this was not a line-by-line read of
  everything, and claiming otherwise would be dishonest. Risk-bearing modules
  (`oauth.py`, `credentials.py`, `session.py`, `usage_store.py`, `menubar.py`,
  `settings.py`, `autoswitch.py` lifecycle) were read directly. Pure-rendering
  code (`tui/*`, `appearance.py`, `printer.py`) and the bulk of `switcher.py`
  were cleared by exhaustive grep for network, subprocess, eval, obfuscation,
  and env-harvest constructs — which returned zero hits. The network-surface
  guarantee rests on that grep being exhaustive over *all* `.py` files, which it
  is.
- This clears phone-home / exfiltration / backdoor concerns. It is not a general
  vulnerability assessment of every edge case in credential handling, and it
  does not audit the transitive dependency tree's own source.

## Re-checking future releases

`scripts/redflag.sh` automates this audit for any version: it verifies the
published artifact's SHA256 against PyPI metadata, lists every network host
(flagging any outside the Anthropic/PyPI allowlist), surfaces exec/obfuscation
constructs, and diffs the security-relevant delta against a baseline.

```bash
scripts/redflag.sh                          # latest stable vs your installed version
scripts/redflag.sh 0.27.0                   # a specific version
scripts/redflag.sh 0.27.0 --baseline 0.25.0 # delta vs this audited version

# Compare against the release commit rather than the working tree. The repo
# publishes no tags, so pass the "version bump" commit for that release —
# find it with:  git log --oneline -S 'version = "0.27.0"' -- pyproject.toml
scripts/redflag.sh 0.27.0 --repo . --git-ref <bump-commit>
```

Exit code `0` = no red flags; `1` = an unknown host, a new risky construct in
the delta, or a SHA256 mismatch. It is a known-bad-pattern scanner, not a proof
of safety — always read its output. In particular, its delta check flags *any*
added line touching network/exec/env constructs, which on a large release will
fire on benign code: treat that output as a review queue, not a verdict.
