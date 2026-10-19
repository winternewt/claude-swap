# Downstream seat — notes

State as of 2026-10-17.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-10-16. Its code is `59d9ffb` (gated); before
  that it pointed at `d138f8d`. The history is in SECURITY_AUDIT.md's marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.79; its watchdog was restarted on that copy by `stop` + `punch-in`.
- **Standing adoption, behind the gate** (the person, 2026-10-17: "auto-adopt further ones";
  2026-10-18: "build the gate and threat model, this repo is sensitive"). An announcement in
  `announcements` from the admin seat or a person on the team, of a tag that exists on the kit:
  1. `scripts/kitgate.py vOLD vNEW`. Exit 0: go on. Exit 1: read every listed hunk in full, add a
     row to SECURITY_AUDIT.md's kit table, and put the move to the person (chat, or the desk when
     away, default "stay on vOLD"). Exit 3 or 4: the same, recommending against unless the reading
     explains it.
  2. The three `claude plugin` commands (marketplace add `#vNEW`, install, update, all
     `--scope project`).
  3. `scripts/kitgate.py vNEW vNEW --copy ~/.claude/plugins/cache/agent-seat-blueprints/seats/NEW`.
     Not 0: move the pin back the same way, and put it to the person.
  4. Add the row to SECURITY_AUDIT.md's kit table, update the version above, commit those with
     `.claude/settings.json`, push `main`.
  5. `watchdog.py stop` + `punch-in downstream` with `CLAUDE_PLUGIN_ROOT` on the new copy, then
     `watchdog.py react ID` on the announcement, and say the move in the chat in one line.

  Several releases announced at once go as one move to the newest, gated as one diff.
- The kit has no watch on its release tags (filed #36, now the kit lead's L15); the announcement is
  the trigger.

## Upstream

- Last release adopted: `v0.27.2`, and `upstream/main` through `8fdc89a` (the `0.28.0b1` bump),
  merged at `a410e87`. No release is waiting.

## Open with the person

- Nothing. Desk #42 was answered 2026-10-19 (option 1): the pin moved to v0.1.79, the setup line
  (`… | sh -s <seat>`, printed for the person) accepted as safe here.
