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
| The seats kit, `github.com/winternewt/agent-seat-blueprints`, at the tag `.claude/settings.json` pins | **trusted** | The person's own repository, pinned by tag. Its hooks and watchdog run in every session here, and a pin move is a commit the person approves. | the person, 2026-10-16 |

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
