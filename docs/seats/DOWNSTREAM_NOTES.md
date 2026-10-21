# Downstream seat — notes

State as of 2026-10-21.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-10-16. Its code is `59d9ffb` (gated); before
  that it pointed at `d138f8d`. The history is in SECURITY_AUDIT.md's marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.84; its watchdog was restarted on that copy by `stop` + `punch-in`.
- **Standing adoption, behind the gate** (the person, 2026-10-17: "auto-adopt further ones";
  2026-10-18: "build the gate and threat model, this repo is sensitive"; 2026-10-21: the kit can no
  longer move this pin, so the seat tracks it itself). The trigger is the seat's watcher
  (`[seat.downstream.watch.kit]`, `scripts/kittrack.py watch`, every 15 minutes) or an announcement
  in `announcements`, whichever comes first:
  1. `scripts/kittrack.py move vNEW --trailer 'Co-Authored-By: …'`. It gates `vOLD vNEW`, moves the
     pin and the client's copy, holds the copy against the tag, records the row in SECURITY_AUDIT.md
     and the version above, commits the three files and restarts the seat's watchdog on the new copy.
     A copy that fails the check is moved back (exit 4).
  2. Exit 1 (read): read every listed hunk in full, add a row to SECURITY_AUDIT.md's kit table, and put
     the move to the person (chat, or the desk when away, default "stay on vOLD"). On their yes,
     `move vNEW --approved 'WHERE'` (where they said it); it passes a read, never a 3 or a 4. Exit 3 or 4: the
     same, recommending against unless the reading explains it.
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

- Desk #55 (filed 2026-10-21, updated the same day for v0.1.86): move the kit pin from v0.1.84.
  Answers: "1" → v0.1.86, "1.85" → v0.1.85, "2" or silence → stay. Both read safe (SECURITY_AUDIT.md).
  Verify the answer on the issue itself. "1.85": `scripts/kittrack.py move v0.1.85 --approved 'desk #55'`.
  "1": v0.1.84 → v0.1.86 gates hard (the renamed forge-gate pipe), which `--approved` never passes, since
  a moved tag is hard too: first `scripts/kitgate.py v0.1.84 v0.1.86` and confirm its only HARD line is
  hooks/forge-gate.sh:16, then the procedure's steps by hand (the three client commands, `kitgate.py
  v0.1.86 v0.1.86 --copy`, the row, the commit, the restart).
