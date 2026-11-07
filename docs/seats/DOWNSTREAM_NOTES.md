# Downstream seat — notes

State as of 2026-11-04.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-11-04. Its code is `babc945` (the merge of upstream
  `v0.29.0`, gated); before that it pointed at `a2b2f43` (code `59d9ffb`). The history is in SECURITY_AUDIT.md's
  marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.127; its watchdog was restarted on that copy by `stop` + `punch-in`.
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

- Last release adopted: `v0.29.0` (with `v0.28.0`), merged at `babc945` on 2026-11-04. `upstream/main` carries 21
  more commits past it, not merged; they wait for the next tag. The merge keeps the fork's `UPGRADE_COMMANDS` and
  drops upstream's release-cooldown notice (it points at `uv tool upgrade`); expect that conflict again in
  `update_check.py` and `tests/test_update_check.py`.

## Open with the person

- **Desk #197** (filed 2026-11-05, S3; since its third Update, 2026-11-07, asks to accept two lines for v0.1.140: the onboard.py one below and `scripts/wake-corpus.py` `BUTTON = re.compile(r"watchdog\.(?:py|sh)\S*\s+nothing\b")`, a regex the gate reads as a pipe to shell; v0.1.131 to v0.1.140 read safe): kit v0.1.128 stopped on one hard line, `bin/onboard.py:1080`
  `| sh -s {names}{' --overlay' if over else ''}`, the accepted `| sh -s {names} --overlay` line merged with its
  twin. Read safe (SECURITY_AUDIT.md kit table, 5bdb0ec). Default: stay on v0.1.127. On yes: swap the old line for
  the new text in `scripts/kitgate-accepted.txt` and add the wake-corpus.py line, then `kittrack.py move v0.1.140 --approved 'desk #197'` (or the newest), push, and
  react to the v0.1.128 (637660339), v0.1.129 (637691863), v0.1.130 (637709914), v0.1.131 (637720775), v0.1.132 (637724911), v0.1.133 (637746241), v0.1.134 (637940621), v0.1.135 (637944017), v0.1.136 (637955580), v0.1.137 (638192777), v0.1.138 (638360835), v0.1.139 (638362702) and v0.1.140 (638370441) announcements.
- Desk #110 (filed 2026-10-24 for v0.1.89, moved by comments to v0.1.124) is answered: on 2026-11-04 the
  person accepted the five hard lines that stopped every release ("mark these lines as benign", in chat, put on
  #110 as comment 6637218216). They are listed in `scripts/kitgate-accepted.txt` (d6194f2), and the pin moved
  to v0.1.124 through `kittrack.py move --approved` (d86b621). Left with the person: `/reload-plugins`; the
  auto-mode rules from `bin/automode.py`, one entry per rule plus the environment entry, the old single
  allow entry removed; rule 10 (run the desk's bootstrap from a pasted hand-off) left out unless they seat new
  repos. From v0.1.116 the forge gate fails closed: never prune the old plugin copy under a running session.
  The plugin agent fault-finder (v0.1.122) runs on this repo only on the person's word. A later release: the
  watcher names it, `kittrack.py move vNEW --approved 'standing grant 2026-10-21'` once the read is judged safe;
  a new hard line goes to the person, and #110's form (a bare `**Update:**` line) for any new desk item.
