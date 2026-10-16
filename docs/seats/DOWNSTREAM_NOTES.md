# Downstream seat — notes

State as of 2026-10-16.

## Marker

- `audited` (a tag) → the commit that moved it on 2026-10-16. Its code is `59d9ffb` (gated); before
  that it pointed at `d138f8d`. The history is in SECURITY_AUDIT.md's marker table.
- It moves under the kit's D101 grant: only `refs/tags/audited`, only to a descendant, with the old
  commit recorded first.
- The seat runs on kit v0.1.34; its watchdog was restarted on that copy by `stop` + `punch-in`.

## Upstream

- Last release adopted: `v0.27.2`, and `upstream/main` through `8fdc89a` (the `0.28.0b1` bump),
  merged at `a410e87`. No release is waiting.

## Open with the person

- Nothing. The trust register (`docs/TRUST.md`) was started on 2026-10-16: upstream is `audit`, the seats kit
  is `trusted`.
