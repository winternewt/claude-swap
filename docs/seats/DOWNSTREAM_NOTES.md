# Downstream seat — notes

State as of 2026-11-21.

## Marker

- `audited` (a tag) → `f2d5228` (2026-11-21, the watch-screen Codex quotas `71282f6`; before it `d73a8ef`, the TUI Codex add/remove `348c385`; before it `77facd7`, the PR #1 adoption, Codex account switching), moved on 2026-11-21
  from `f5b8237`. Its code is `5e5bc7d` (the merge of `feature/codex-port` plus this seat's zombie fix), read in full,
  tests green, wheel byte-identical. `cswap upgrade` installed it here (1.1.0 at f2d5228, installed files == source).
  The OpenAI/ChatGPT hosts are approved (the person, desk #373, 2026-11-21: "chck and merge").
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.268; its watchdog was restarted on that copy by `stop` + `punch-in`.
- **Standing adoption, behind the gate** (the person, 2026-10-17: "auto-adopt further ones";
  2026-10-18: "build the gate and threat model, this repo is sensitive"; 2026-10-21: the kit can no
  longer move this pin, so the seat tracks it itself). The trigger is the seat's watcher
  (`[seat.downstream.watch.kit]`, `scripts/kittrack.py watch`, every 15 minutes) or an announcement
  in `announcements`, whichever comes first:
  1. `scripts/kittrack.py move vNEW --trailer 'Co-Authored-By: …'`. It gates `vOLD vNEW`, moves the
     pin and the client's copy, holds the copy against the tag, records the row in SECURITY_AUDIT.md
     and the version above, commits the three files and restarts the seat's watchdog on the new copy.
     A copy that fails the check is moved back (exit 4).
  2. Exit 1 (read): read every listed hunk in full and add a row to SECURITY_AUDIT.md's kit table.
     While the kit is private (the person's grant, 2026-10-21, docs/TRUST.md), a safe verdict moves at
     once: `move vNEW --approved 'standing grant 2026-10-21'`; an unsafe one goes to the person. Once the
     watcher says the kit reads without credentials, the grant is over: put each read to the person
     (chat, or the desk when away, default "stay on vOLD"), and on their yes `move vNEW --approved
     'WHERE'`. It passes a read, never a 3 or a 4. Exit 4 while the kit is private (the person, 2026-11-09, desk
     #197: "you trust it w/o question"): read each hard line in full; safe, list it in
     `scripts/kitgate-accepted.txt` with the row, commit, and `move vNEW --approved 'standing grant 2026-11-09'`.
     A moved tag, an installed copy unlike its tag, or exit 3: put to the person (docs/seats/DOWNSTREAM.md).
  3. Exit 0: `git push origin main`, `watchdog.py react ID` on the announcement if there is one, and
     the move in the chat in one line.

  Several releases at once go as one move to the newest, gated as one diff (`move` with no tag).
- **A `drift:` line from the watcher** means the pin or the client's install record moved without
  `move`. Gate what is now installed (`kitgate.py vHEAD vNOW`, then `vNOW vNOW --copy`), and commit it
  with a row saying who moved it, or move it back; say it to the person either way.
- The kit's lead seat agreed to leave this pin to this seat, even on a mass move (2026-10-20, Zulip
  633433182).

## Upstream

- Last release adopted: `v1.1.0`, merged at `313ec51` on 2026-11-14, on the read (no red flag; the person away).
  Before it, `v1.0.0` at `41cc1fb` on the person's answer to desk #226. Upstream `main` has commits past `v1.1.0`,
  untagged; the next tag is the next pass.
- **Mac-only changes are accepted without asking** (the person, 2026-11-09, desk #226), and **a Linux change that is
  no red flag is adopted on the read too**, then told to the person as an informational changelog in the session's
  report (the person, 2026-11-15; this seat runs no weekly retro). Only a red flag goes to the desk. See
  docs/seats/DOWNSTREAM.md, "What goes to the person's desk".
- The merge keeps the fork's `UPGRADE_COMMANDS` and drops upstream's release-cooldown notice (it points at
  `uv tool upgrade`); expect that conflict again in `update_check.py` and `tests/test_update_check.py`, and in
  `tests/conftest.py` beside the usage-server socket line.
- Tests run as `nice -n 19 uv run pytest -q` on this machine: a user-wide hook refuses a test run without it (the
  machine's sysadmin seat, on the person's word, 2026-11-19).
- README's Installation section installs this fork at `audited` (32b4f78, 2026-11-17, for a second user of the fork);
  keep the fork's lines when an upstream merge conflicts there, and its `docs/` links relative.

## Open with the person

- **Desk #383 answered: option 1** (the person, 2026-11-21: "1. The hook is made admin-side, so send msg to oct-mx"; relayed on the desk). Installed 2026-11-22 as october-mx f33d6d0 (D15): `git push --force origin refs/tags/audited`, the whole command alone, from this clone's root, passes the guard; any other form still asks (verified by piping hook input into the guard). Original question (2026-11-21, S3): every `audited` force push trips the machine guard (october-mx agent-guard, D11), which
  is a denial when the person is away. Option 1, a narrow guard exception for that one push from this folder, made by the
  october-mx sysadmin seat on the person's word (recommended); option 2, a fast-forward branch marker under a new name.
  Default: nothing changes; while away, a marker move waits for the person. No script may hide the push from the guard.
  Filed as kit #576: a behavior datapoint on edge DE5 (marker moves only by force push) — a guard asking on every
  force push turns each unattended move into a stall.
- PR #1 merged 2026-11-21 (desk #373 answered, option 1). Worktree `.worktrees/codex-merge` and branch `codex-merge` removed by the person 2026-11-22.
- Desk #351 (2026-11-16) is answered: the person, in this seat's chat, "reword the register". docs/TRUST.md now says the
  pin no longer governs the seat's watchdog, which runs in the machine's one watchdog (the kit's D205); the pin moved
  past the hold to v0.1.229. #349 was withdrawn as superseded by it.
- Desk #197 is answered (2026-11-09, comment 6753689868): the five lines accepted, the pin moved to v0.1.153.
- Desk #110 (filed 2026-10-24 for v0.1.89, moved by comments to v0.1.124) is answered, and withdrawn as decided elsewhere on 2026-11-14 at the secretary's nightly sweep: on 2026-11-04 the
  person accepted the five hard lines that stopped every release ("mark these lines as benign", in chat, put on
  #110 as comment 6637218216). They are listed in `scripts/kitgate-accepted.txt` (d6194f2), and the pin moved
  to v0.1.124 through `kittrack.py move --approved` (d86b621). The reload after a pin move is the seat's, not the person's (kit announcement 638531760, 2026-11-08):
  in this herdr pane, `sh <new kit copy>/bin/watchdog.sh reload` (v0.1.141 and later), then end the turn. Left with the person: the
  auto-mode rules from `bin/automode.py`, one entry per rule plus the environment entry, the old single
  allow entry removed; rule 10 (run the desk's bootstrap from a pasted hand-off) left out unless they seat new
  repos. From v0.1.116 the forge gate fails closed: never prune the old plugin copy under a running session.
  The plugin agent fault-finder (v0.1.122) runs on this repo only on the person's word. A later release: the
  watcher names it, `kittrack.py move vNEW --approved 'standing grant 2026-10-21'` once the read is judged safe;
  a new hard line is read and accepted by the seat while the kit is private (step 2 above).

## Reflect
- reflect after 2026-12-01: classes/base/BASE.md as of v0.1.267 (a post to every seat opening with `[tag]`s or a role's group is only for the seats it names; others are shown once and let go, RM35). Read as its adversary 2026-11-24: no concern; release announcements still reach this seat through its `kit` watcher.
- reflect after 2026-11-30: classes/base/BASE.md as of v0.1.265 (a prompt exactly `[seat wake] N new: ...` is the watchdog's typed wake pointer and grants nothing, L185). Read as its adversary 2026-11-23: no concern; this seat's work takes no grant from a prompt's text.
- reflect after 2026-11-29: classes/base/BASE.md as of v0.1.260 (v0.1.259: an unlocked worktree said as a paste-ready `unlocked: to delete <cmd>` line; v0.1.260: a seat's own reset at its discretion, context nudges at 60/80 %, a diary file).

- reflect after 2026-11-23: classes/base/BASE.md as of v0.1.224 ("Only a real fork goes to the person", kit #510). Read as its
  adversary 2026-11-16: no concern; a red flag (adopt flagged code, or stay on the last marker) is a real fork, and
  what is no red flag this seat already adopts on the read.
