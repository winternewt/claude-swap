# Trust register

claude-swap reads, refreshes and stores Claude Code OAuth tokens for several accounts. A stolen
refresh token is a stolen login, so this repository keeps a register (the seats kit's base, "Code
from elsewhere, where a repo holds private things").

**The rule:** before code from outside this repository's own history runs here in any way (tests, an
install, a build, a hook, a launch), check its source's standing below.

- **trusted**: it runs.
- **audit**: the whole incoming change is read first. Every file outside what it claims to do is
  named, and so is every place that runs by itself: build config, test fixtures, git hooks, CI, agent
  settings and instructions. The person approves before anything executes.
- **untrusted**: read, never run.

A source that is not listed is untrusted. Only the person sets a standing; a session never raises
one itself.

## Sources

| Source | Standing | Why | Decided |
|---|---|---|---|
| `upstream`, `github.com/realiti4/claude-swap`: its commits, its tags and its PyPI releases | **audit** | Third-party code that handles the tokens. Every release is read in full and its artifacts are checked against the source before a merge or an install. That pass is the downstream seat's (`docs/seats/DOWNSTREAM.md`), and its record is `SECURITY_AUDIT.md`. | the person, 2026-10-16 |
| The seats kit, `github.com/winternewt/agent-seat-blueprints`, at the tag `.claude/settings.json` pins | **trusted, behind a gate** | The person's own repository, but its releases are cut by agent seats with no person reading them, and its code runs here beside the logins. Each pin move passes `scripts/kitgate.py`; see the threat model below. | the person, 2026-10-16; the gate 2026-10-18; the tracker 2026-10-21 |

## The seats kit: threat model

- **What it runs here.** Hooks on every session event (start, each prompt, stop, compaction, a
  message to another session), through `bin/py` and `classes/base/watchdog.py`. The seat's watchdog
  in the background, with its Zulip driver. The quota watcher (`drivers/claude-code/quota.py`),
  which reads `~/.claude/.credentials.json` and sends the access token to `api.anthropic.com`, a URL
  that `QUOTA_URL` can override. Its skills, commands and agents when called. And its instructions
  (the base, the downstream role, its rules), which steer every session here.
- **The harm that matters: a login leaving the machine.** The kit already holds everything that
  would take: a token in hand, clients that send (Zulip, GitHub through `gh`, the usage endpoint),
  and sessions that follow its instructions. A release could turn any of them into a leak without
  a new dependency or a new host.
- **Who writes it.** The person's own repository, but agent seats write and tag its releases
  (`bin/release`); about 25 came out from 2026-10-16 to 2026-10-18. While the kit stays private and
  the person is its only builder, the person holds it secure (2026-10-21); the distrust above is for
  when it goes public, and the gate is what stands then. Until then the gate stays as it is: a clean
  move costs nothing.
- **Who moves the pin.** Only this repo's own seat, with `scripts/kittrack.py move`. The kit's
  `bin/move-to-tag` can repin any clone on this machine from outside it, and on 2026-10-20 the kit's
  lead seat did so here (v0.1.82 → v0.1.84), ungated, and a session resumed on the new copy before
  any check: the person's one-time mitigation for a pending restart, not the procedure. The lead
  seat has since agreed to leave this pin alone, even on a mass move.
- **The control.** Before each pin move, `scripts/kitgate.py OLD NEW` (record and method in
  SECURITY_AUDIT.md, "The seats kit's pin moves"):
  - **clean** (exit 0): the pin moves without asking, and the move is reported;
  - **read** (exit 1): the seat reads every listed hunk in full, records its verdict, and puts the
    move to the person; the pin stays meanwhile;
  - **hard** (exit 4) or **unknown** (exit 3): the pin stays, and the person decides with the hunks.

  After the move, `kitgate.py NEW NEW --copy <installed copy>` holds what the client installed
  against the tag, before the watchdog restarts on it or a session reloads it. A mismatch moves the
  pin back. `scripts/kittrack.py move` runs all of it in that order.

  The seat's watcher (`kittrack.py watch`, every 15 minutes) names a newer release, and a **drift**:
  the tracked pin moved in the tree without a commit, or the client's install record for this clone
  at another version. Either means a move outside the gate; the seat gates what is installed and
  says it to the person.
- **The risk accepted.** What the gate's patterns do not name: a host built at run time, a leak
  through a client and host the kit already uses by a line no pattern matches, an instruction
  changed in a file outside the set a session here loads. Also the minutes between the client's
  `plugin update` and the `--copy` check, in which a newly started session would load the new copy.
  And a move from outside: the drift line comes up to 15 minutes after it, and a session started
  in between runs the copy ungated, as on 2026-10-20.

## Outside the rule

- **This repository's own history**, `origin` (`github.com/winternewt/claude-swap`), including what it
  merged from `upstream` after an audit.
- **Packages pinned in `uv.lock` from the package index**: the pin is their standing. A new or changed
  runtime dependency still shows up in the audit's `Requires-Dist` check.
- **The person's user-level Claude Code setup**, for example the `just-module-creator` plugin. It
  loads in sessions here, but this repository does not pull it in, so it has no standing in this
  register (the person, 2026-10-16).

## Not listed, so untrusted

Pull requests and branches from other forks, before `upstream` merges them. Code pasted in from an
issue or a chat. Any script or file another session leaves in the working tree uncommitted.
