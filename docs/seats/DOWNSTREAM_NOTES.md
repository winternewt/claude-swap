# Downstream seat — notes

State as of 2026-10-16.

## Marker

- `audited` (a tag) → `d138f8d`: the `70dde18` code plus its audit record. This is what
  `cswap upgrade` installs, and it is installed on this machine.
- `main` → `5ba6d52`, gated through `59d9ffb` (menu bar hint text only; see SECURITY_AUDIT.md).
- **Pending: move the marker to `5ba6d52`.** It is a tag, so moving it needs
  `git push -f origin refs/tags/audited`, and no seat grant covers a force push. The person chose to
  wait for the kit to allow a grant for this one tag (2026-10-16), rather than make the marker a branch.

## Upstream

- Last release adopted: `v0.27.2`, and `upstream/main` through `8fdc89a` (the `0.28.0b1` bump),
  merged at `a410e87`. No release is waiting.

## Open with the person

- A trust register (`docs/TRUST.md`): the base asks once, because this repo handles OAuth tokens.
  Not asked yet.
