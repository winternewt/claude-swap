# Security Audit — claude-swap

**Scope:** Does `claude-swap` phone home, exfiltrate credentials, or contain a
backdoor? It handles Claude Code OAuth tokens, so the bar is: tokens must never
leave the machine except to Anthropic's own endpoints.

**Audit date:** 2026-06-25
**Versions audited:** `0.15.0b1` (full read) and `0.14.0` (delta + integrity)
**Auditor:** independent review on the `winternewt` fork
**Method:** full source read + byte-for-byte diff of the published PyPI
artifacts against the git source.

---

## Verdict: ✅ Clean

No phone-home, no data exfiltration, no backdoor. Safe to expose Claude Code
OAuth tokens to both the current stable (`0.14.0`) and the beta (`0.15.0b1`).

This is, if anything, *defensively* written code — it pins the macOS `security`
binary by absolute path, keeps secrets out of `argv`, scrubs auth env vars
before launching `claude`, and strips machine-identity fields from exports.

---

## Network surface — complete, 3 endpoints, all hardcoded literals

Every outbound connection the code can make:

| Endpoint | Method | What is sent | Source |
|---|---|---|---|
| `https://platform.claude.com/v1/oauth/token` | POST | `refresh_token` + Claude Code's public `client_id` (`9d1c250a-…`) — standard OAuth refresh | `oauth.py:16,68` |
| `https://api.anthropic.com/api/oauth/usage` | GET | `Authorization: Bearer <access_token>` — to read usage % | `oauth.py:149` |
| `https://pypi.org/pypi/claude-swap/json` | GET | **nothing** — anonymous, reads only the version field | `update_check.py:16` |

- All three URLs are **hardcoded string constants**, not built from config or
  environment, so they cannot be silently redirected.
- Credentials are sent **only** to Anthropic's two own domains. There is no
  code path that transmits tokens, the refresh token, or environment data
  anywhere else.
- A full-tree grep for `socket`, `requests`, `httpx`, `aiohttp`, `smtplib`,
  `ftplib`, `http.client`, and base64/hex/pickle/marshal obfuscation returned
  nothing beyond the items above. No `os.environ` value feeds any request.

## Process / execution surface

- `subprocess` is used only in: `macos_keychain.py` (the system `security` CLI),
  `update_check.py` (`uv tool upgrade` / `pipx upgrade`, hardcoded arg-arrays),
  and `session.py` (`os.execvpe`/`subprocess.run` of the `claude` binary).
- **No `shell=True` anywhere.** No `eval`, `exec`, `os.system`, `os.popen`,
  `pickle`, `marshal`, or `__import__` of attacker-controllable input.
- No background threads, timers, `atexit` hooks, signal handlers, or
  import-time side effects — the tool runs synchronously and exits, so nothing
  lingers to phone home later.

## Things that raised confidence (good security hygiene)

- **`/usr/bin/security` is pinned by absolute path** to stop a PATH-planted fake
  binary from intercepting Keychain secrets (`macos_keychain.py:60`); secrets
  are passed via stdin, never `argv`.
- **Auth env vars are scrubbed** from the child environment before `claude` is
  launched (`session.py:178,244`).
- **Export strips machine-identity fields** (userID, anonymousId, paths) and
  writes only to stdout or a local `0600` file the user names — no auto-upload
  (`transfer.py`, `_slim_config`).
- **Import has explicit path-traversal guards** on email/slot before any
  filename is constructed (`transfer.py`, `_validate_imported_account`).
- `base64` appears only for **local** per-account credential backup `.enc`
  files — encode-to-disk / decode-from-disk, not obfuscation.
- No custom `keyring` backend is registered (`set_keyring` is absent), so the
  default OS keystore is used.

## Dependencies

One runtime dependency: `keyring`, pulling only its standard transitive set
(`secretstorage`/`jeepney`/`cryptography` on Linux, `pywin32-ctypes` on Windows,
`colorama`, `jaraco-*`, `more-itertools`). `pytest` is dev-only. No typosquats,
nothing exotic.

---

## Supply-chain verification (published artifact == source)

The audited GitHub source is not automatically what `uv tool install` pulls —
the PyPI package is published by `realiti4`, and this is the `winternewt` fork.
So the published artifacts were diffed against the git source directly.

### `0.15.0b1` (beta) — published == fork source, byte-for-byte
All 21 `.py` files in the published wheel **and** sdist are SHA256-identical to
`src/claude_swap/` at commit `8fea1c6`.

```
wheel  sha256: 4ab7f41583553d040f67a3c2078df28d425c7ec83f49bd38b909cdc8b98b7f0a
sdist  sha256: 93e62a9298fd890fb0c4ea58a404f50fb228868248925f2e623039bf9a6df415
```

### `0.14.0` (current stable, what a plain install gets) — clean by transitivity
- Published `0.14.0` is byte-for-byte identical to the repo at commit `a207d31`
  (21/21 `.py` SHA256 match).
- The delta `0.14.0 → 0.15.0b1` (+589/−93 lines across `cli.py`,
  `credentials.py`, `json_output.py`, `session.py`, `switcher.py`,
  `transfer.py`) touches **zero** network/exec/url/env/obfuscation code — it is
  entirely the API-key account feature (PR #72) and active-account token-refresh
  logic.
- Therefore `0.14.0`'s exfil surface is a strict subset of the fully-audited
  `0.15.0b1`. Clean.

```
wheel  sha256: 75ebce7433dd936b3b95ba34d905f29848ec4bb559e0d416ec3978ea5b9a1f6f
sdist  sha256: 6c1aab1988348214d8cfcfeb97d6b8f6e9077fb4847917fc0abf1cc57a7376c9
```

> Note: the repo committed `0.14.1`, but it was never published to PyPI — a
> plain `uv tool install claude-swap` resolves to `0.14.0`.

### To run exactly an audited version

```bash
uv tool install 'claude-swap==0.14.0'      # current stable — verified clean
uv tool install 'claude-swap==0.15.0b1'    # beta — fully read + verified clean
```

---

## Limits of this audit

- Verification is **per-version**. Any future release is unaudited until
  re-checked — the maintainer can publish a new artifact at any time.
- This clears phone-home / exfiltration / backdoor concerns. It is not a general
  vulnerability assessment of every edge case in credential handling.

## Re-checking future releases

`scripts/redflag.sh` automates this audit for any version: it verifies the
published artifact's SHA256 against PyPI metadata, lists every network host
(flagging any outside the Anthropic/PyPI allowlist), surfaces exec/obfuscation
constructs, and diffs the security-relevant delta against a baseline. Run it
before upgrading:

```bash
scripts/redflag.sh                 # latest stable vs your installed version
scripts/redflag.sh 0.16.0          # a specific version
scripts/redflag.sh 0.16.0 --repo . # also diff published vs this checkout
```

Exit code `0` = no red flags; `1` = an unknown host, a new risky construct in
the delta, or a SHA256 mismatch. It is a known-bad-pattern scanner, not a proof
of safety — always read its output.
