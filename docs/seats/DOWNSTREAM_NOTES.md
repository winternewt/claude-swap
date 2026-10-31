# Downstream seat — notes

State as of 2026-10-21.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-10-16. Its code is `59d9ffb` (gated); before
  that it pointed at `d138f8d`. The history is in SECURITY_AUDIT.md's marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.88; its watchdog was restarted on that copy by `stop` + `punch-in`.
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
     'WHERE'`. It passes a read, never a 3 or a 4. Exit 3 or 4: put to the person, recommending against
     unless the reading explains it.
  3. Exit 0: `git push origin main`, `watchdog.py react ID` on the announcement if there is one, and
     the move in the chat in one line.

  Several releases at once go as one move to the newest, gated as one diff (`move` with no tag).
- **A `drift:` line from the watcher** means the pin or the client's install record moved without
  `move`. Gate what is now installed (`kitgate.py vHEAD vNOW`, then `vNOW vNOW --copy`), and commit it
  with a row saying who moved it, or move it back; say it to the person either way.
- The kit's lead seat agreed to leave this pin to this seat, even on a mass move (2026-10-20, Zulip
  633433182).

## Upstream

- Last release adopted: `v0.27.2`, and `upstream/main` through `8fdc89a` (the `0.28.0b1` bump),
  merged at `a410e87`. No release is waiting.

## Open with the person

- Desk #110 (filed 2026-10-24 for v0.1.89; comments on 2026-10-25 moved it to v0.1.90, v0.1.91, v0.1.92, v0.1.93,
  v0.1.94, then (2026-10-26) v0.1.95, then (2026-10-27) v0.1.96, v0.1.97 and v0.1.98, then (2026-10-31) v0.1.99, each superseding the last): move the kit pin from v0.1.88 to v0.1.99. Answers: "1" → move, "2" or silence →
  stay. It gated hard (the repo-rename skill's `persistence` line, and two `pipe to shell` lines that print
  the person's bootstrap command, never run), read safe (SECURITY_AUDIT.md). Verify the answer on the issue
  itself. On "1": `scripts/kitgate.py v0.1.88 v0.1.99`, confirm its only HARD lines are those four (repo-rename:42,
  host-move:124, onboard.py:913 and :921), then the
  move by hand as for v0.1.86 (the tracker's own client, `--copy` gate and move-back, then the row, the
  commit, the restart), since `--approved` never passes a hard stop. v0.1.91's punch-in refuses a session
  without the plugin's hooks; this one passes. From v0.1.92 the prompt hook types `/reload-plugins` into the
  session's herdr pane itself when the pin is ahead. From v0.1.93 the forge gate checks unseated sessions only
  because `.blueprints.toml` sets `forge_gate_unseated = true`: keep it. From v0.1.96 the watchdog runs that
  reloader itself every minute. From v0.1.99 the plugin loads a UI module (a status line, a band while the quota
  hold is on, `/seats-view`). A later release: gate it against
  v0.1.88 and update #110 the same way, the comment opening with a bare `**Update:**` line (the desk's
  protocol line from kit v0.1.98; `**Update (date):**` is not read as one).
