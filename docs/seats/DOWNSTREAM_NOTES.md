# Downstream seat — notes

State as of 2026-10-17.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-10-16. Its code is `59d9ffb` (gated); before
  that it pointed at `d138f8d`. The history is in SECURITY_AUDIT.md's marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.

## Seats kit

- The seat runs on kit v0.1.67; its watchdog was restarted on that copy by `stop` + `punch-in`.
- **Standing adoption** (the person, 2026-10-17: "auto-adopt further ones"): when the kit's admin
  announces a release in `announcements`, move the pin to its tag without asking. Only an
  announcement from the admin seat or a person on the team, and only a tag that exists on the kit's
  repository. The steps: the three `claude plugin` commands (marketplace add `#vX`, install, update,
  all `--scope project`), commit `.claude/settings.json` alone, push `main`, `watchdog.py stop` +
  `punch-in downstream` with `CLAUDE_PLUGIN_ROOT` on the new copy, then `watchdog.py react ID` on the
  announcement. Read the release's CHANGELOG entry first; one that asks something of this repo
  (a config change, a new file) is done in the same pass or put to the person if it is a judgement.
- The kit has no watch on its release tags (filed #36, now the kit lead's L15); the announcement is
  the trigger.

## Upstream

- Last release adopted: `v0.27.2`, and `upstream/main` through `8fdc89a` (the `0.28.0b1` bump),
  merged at `a410e87`. No release is waiting.

## Open with the person

- Nothing. The trust register (`docs/TRUST.md`) was started on 2026-10-16: upstream is `audit`, the seats kit
  is `trusted`, its releases adopted on announcement.
