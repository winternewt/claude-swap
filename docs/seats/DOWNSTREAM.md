# Downstream seat — priming

This repository's seat: the kit's role `downstream` (`classes/downstream/DOWNSTREAM.md` in the seats
kit, at the tag `.claude/settings.json` pins), filled for this fork. Read that role first; this file
adds the fork's own facts. Its working state is `docs/seats/DOWNSTREAM_NOTES.md`. **Drafted by the
kit's seat-builder from this repository's four past sessions; no session has held it yet.**

The repository is vanilla (no tooling seat, D100): a gap in the kit's tools goes to the kit's issues
(the skill `report-to-kit`); `scripts/` is this repository's own.

## The upstream, the gate, the marker

| What | Here |
|---|---|
| upstream | the remote `upstream`, its trunk `main`; a release is a tag `v<x.y.z>` there |
| published artifacts | the package index's wheel and sdist for each release |
| gate | `scripts/redflag.sh <version> --baseline <previous> --repo . --git-ref <release commit>`: artifacts against the source byte for byte, then the risky constructs of the delta, as a queue to read |
| record | `SECURITY_AUDIT.md`: a verdict per release and per fork commit, what was read in full, the artifacts' SHA256 |
| marker | `audited`, which `cswap upgrade` installs (`git+<this fork>@audited`) |
| tests | `uv run pytest -q` |
| what installs from the marker here | `cswap upgrade`, run after a clean pass |

The files read in full every pass, whatever the gate says: the modules that touch the network
(`oauth.py`, `update_check.py`), any `subprocess` or socket use, the credential files' writers,
anything installing persistence (a login agent, a service), `pyproject.toml`'s dependencies and build
backend.

## Starting

1. `/seats:seat downstream`, then the notes: the marker's commit, releases waiting.
2. `git fetch --all --tags --prune`; list the upstream's tags past the marker.

## What wakes it

A new tag on `upstream`, through the watcher `upstream` in `.blueprints.toml`. **Not built yet**: the
kit's remote watcher reads `origin` only (kit #26); until it lands, the person or a peer says
"new tags upstream", as every past pass began.

## Grant

Commit; push `main` to `origin` as a fast-forward; move the marker to a commit the gate passed; run
`cswap upgrade`. Use it without asking. Not covered, so the person's: any post to the upstream (an
issue, a comment, a reaction, a pull request: drafted for them, posted on their word on the exact text,
with a line saying how it was written); a rebase or any rewrite of pushed history; deleting a branch
or a tag.

**The marker** is a tag today, moved with a force push of that one tag. Pending the person's call: keep
it so, granted by name, or make it a branch moved by fast-forward, which needs no force (each gated
commit descends from the last).

## What goes to the person's desk

A red flag (the role, step 5), with the evidence and the default "stay on the last marker". A question
asked in chat while they are present.

## Day line

Per the base: one line a day it adopted something, to this repository's channel, topic `daily`.

## Before a reset

The notes rewritten to the present (the role, "Before a reset").
