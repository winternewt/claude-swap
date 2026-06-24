#!/usr/bin/env bash
#
# claude-swap-redflag.sh — pre-upgrade supply-chain check for the `claude-swap`
# PyPI package. Run this BEFORE `uv tool upgrade claude-swap` to confirm a new
# release hasn't grown a phone-home path, a new network host, or obfuscation.
#
# What it does (no install, read-only):
#   1. Pulls the published wheel + sdist from PyPI and verifies each download's
#      sha256 against PyPI's own metadata (detects a tampered CDN object).
#   2. Extracts every .py and lists all network hosts it references, marking
#      each KNOWN (Anthropic / PyPI) or *** NEW *** (anything else = red flag).
#   3. Surfaces exec/subprocess/eval/obfuscation/env-harvest constructs for eyeballing.
#   4. Diffs the security-relevant delta vs a baseline version (default: the
#      version you currently have installed) so you only re-read what changed.
#   5. Optionally confirms the published artifact == a local git checkout.
#
# Exit code 0 = nothing alarming; 1 = at least one red flag (NEW host, new
# exec/obfuscation construct vs baseline, or a sha mismatch). Always read the
# output — a clean exit is "no known-bad pattern", not a proof of safety.
#
# Usage:
#   ./claude-swap-redflag.sh                       # check latest stable vs installed
#   ./claude-swap-redflag.sh 0.16.0                # check a specific version
#   ./claude-swap-redflag.sh 0.16.0 --baseline 0.15.0b1
#   ./claude-swap-redflag.sh 0.16.0 --repo /data/sources/claude-swap
#
set -euo pipefail

PKG="claude-swap"
DIST="claude_swap"          # sdist/wheel use the underscore form
PYPI="https://pypi.org/pypi/${PKG}/json"

# --- Known-good network hosts. Anything else found in the code is a RED FLAG.
# Trailing-comment hosts (docs) are fine to appear here too; keep the list tight.
KNOWN_HOSTS=(
  "api.anthropic.com"           # usage API (Bearer access token)
  "platform.claude.com"         # OAuth token refresh
  "pypi.org"                    # update check (anonymous)
  "files.pythonhosted.org"      # PyPI CDN
  "no-color.org"                # doc link in printer.py
  "specifications.freedesktop.org"  # doc link in paths.py
  "github.com"                  # project URLs / docs
)

VERSION=""
BASELINE=""
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --baseline) BASELINE="$2"; shift 2 ;;
    --repo)     REPO="$2"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          VERSION="$1"; shift ;;
  esac
done

for bin in curl python3 sha256sum tar unzip diff; do
  command -v "$bin" >/dev/null || { echo "missing required tool: $bin" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
RED=0   # red-flag counter

note()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
flag()  { printf '  \033[31m*** RED FLAG: %s ***\033[0m\n' "$*"; RED=$((RED+1)); }
ok()    { printf '  \033[32m%s\033[0m\n' "$*"; }

curl -sS --max-time 30 "$PYPI" -o "$WORK/meta.json"

# Resolve target version (default: latest non-prerelease) and baseline (default:
# currently-installed, if cswap is on PATH).
if [ -z "$VERSION" ]; then
  VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["info"]["version"])' "$WORK/meta.json")"
fi
if [ -z "$BASELINE" ] && command -v cswap >/dev/null 2>&1; then
  BASELINE="$(cswap --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+[0-9a-z.]*' | head -1 || true)"
fi

note "Target: ${PKG} ${VERSION}   Baseline: ${BASELINE:-<none>}"

# --- Download + integrity-verify one version's artifacts; extract .py into $2.
fetch_and_extract() {
  local ver="$1" outdir="$2"
  mkdir -p "$outdir/code"
  python3 - "$WORK/meta.json" "$ver" <<'PY' > "$WORK/files.$ver" || { echo "version $ver not on PyPI" >&2; return 3; }
import json,sys
d=json.load(open(sys.argv[1])); v=sys.argv[2]
rel=d["releases"].get(v)
if not rel: sys.exit(1)
for f in rel:
    print(f["filename"], f["digests"]["sha256"], f["url"])
PY
  while read -r fname sha url; do
    curl -sS --max-time 120 -o "$outdir/$fname" "$url"
    actual="$(sha256sum "$outdir/$fname" | cut -d' ' -f1)"
    if [ "$actual" != "$sha" ]; then
      flag "$fname sha256 MISMATCH vs PyPI metadata (download != published!)"
    fi
    case "$fname" in
      *.whl)    ( cd "$outdir/code" && unzip -oq "$outdir/$fname" ) ;;
      *.tar.gz) tar xzf "$outdir/$fname" -C "$outdir/code" ;;
    esac
  done < "$WORK/files.$ver"
}

note "Downloading + verifying integrity"
fetch_and_extract "$VERSION" "$WORK/target"
ok "downloaded; sha256 of each artifact checked against PyPI metadata above"

# Locate the package source dir inside whatever got extracted (wheel or sdist).
TGT_SRC="$(dirname "$(find "$WORK/target/code" -name oauth.py | head -1)")"
[ -n "$TGT_SRC" ] || { echo "could not find package source in artifact" >&2; exit 2; }

# --- 1) Network hosts.
note "Network hosts referenced in published code"
python3 - "$TGT_SRC" "${KNOWN_HOSTS[@]}" <<'PY' > "$WORK/hosts.txt"
import os,re,sys
src=sys.argv[1]; known=set(sys.argv[2:])
hosts={}
for root,_,files in os.walk(src):
    for fn in files:
        if not fn.endswith(".py"): continue
        p=os.path.join(root,fn)
        for m in re.finditer(r'https?://([^/\s"\'\\)]+)', open(p,encoding="utf-8",errors="replace").read()):
            hosts.setdefault(m.group(1), set()).add(fn)
for h in sorted(hosts):
    tag="KNOWN" if h in known else "NEW"
    print(f"{tag}\t{h}\t{','.join(sorted(hosts[h]))}")
PY
while IFS=$'\t' read -r tag host files; do
  if [ "$tag" = "NEW" ]; then flag "unknown network host: $host  (in $files)"
  else ok "KNOWN  $host  ($files)"; fi
done < "$WORK/hosts.txt"

# --- 2) Sensitive constructs (informational — eyeball these).
note "Sensitive constructs (for review, not auto-failed)"
if grep -rniE 'eval\(|exec\(|os\.system|os\.popen|\bpopen\b|pickle|marshal|__import__|shell\s*=\s*True|base64|fromhex|codecs\.decode' "$TGT_SRC" \
     --include='*.py' | grep -vE '#.*exec' > "$WORK/constructs.txt"; then
  cat "$WORK/constructs.txt"
  echo "  (note: base64 in credentials.py is local .enc backup encoding — expected)"
else
  ok "no eval/exec/os.system/pickle/shell=True found"
fi

# --- 3) Delta vs baseline: only re-read what changed, flag new risky lines.
if [ -n "$BASELINE" ] && [ "$BASELINE" != "$VERSION" ]; then
  note "Security-relevant delta  ${BASELINE} -> ${VERSION}"
  fetch_and_extract "$BASELINE" "$WORK/base" || true
  BASE_SRC="$(dirname "$(find "$WORK/base/code" -name oauth.py | head -1)")"
  if [ -n "$BASE_SRC" ]; then
    diff -r "$BASE_SRC" "$TGT_SRC" > "$WORK/delta.diff" 2>/dev/null || true
    if [ ! -s "$WORK/delta.diff" ]; then
      ok "no .py differences between $BASELINE and $VERSION"
    else
      # Only ADDED lines (>) that introduce network/exec/obfuscation are flags.
      if grep -E '^> ' "$WORK/delta.diff" \
           | grep -iE 'urllib|requests|httpx|socket|http\.client|urlopen|subprocess|os\.system|popen|eval\(|exec\(|base64|os\.environ|getenv|https?://' \
           | grep -vE '#' > "$WORK/delta.risky"; then
        echo "  Added lines touching network/exec/env/obfuscation:"
        sed 's/^/    /' "$WORK/delta.risky"
        flag "delta introduces network/exec/env constructs — review the lines above"
      else
        ok "delta touches NO network/exec/env/obfuscation code"
      fi
      echo "  Full file-level changes:"
      grep -E '^(diff |Only in|[<>] )' "$WORK/delta.diff" | grep -E '^(diff|Only in)' | sed 's/^/    /' || true
      echo "  (full line diff saved: re-run with the diff below if you want detail)"
    fi
  else
    echo "  baseline $BASELINE not retrievable; skipping delta"
  fi
fi

# --- 4) Optional: published == local git checkout.
if [ -n "$REPO" ] && [ -d "$REPO/.git" ]; then
  note "Published $VERSION  vs  local git repo"
  mism=0
  for f in "$TGT_SRC"/*.py; do
    bn="$(basename "$f")"
    rf="$REPO/src/$DIST/$bn"
    [ -f "$rf" ] || { echo "  only-in-pypi: $bn"; mism=1; continue; }
    [ "$(sha256sum "$f"|cut -d' ' -f1)" = "$(sha256sum "$rf"|cut -d' ' -f1)" ] || { echo "  DIFFERS: $bn"; mism=1; }
  done
  [ $mism -eq 0 ] && ok "published artifact == repo working tree (all .py match)" \
                   || flag "published artifact differs from local repo (see above)"
fi

# --- Verdict.
note "Verdict"
if [ $RED -eq 0 ]; then
  printf '  \033[32mNo red flags. Integrity verified, no unknown hosts, no new risky constructs.\033[0m\n'
  echo   "  Safe to: uv tool install '${PKG}==${VERSION}'"
  exit 0
else
  printf '  \033[31m%d red flag(s) — review above BEFORE upgrading.\033[0m\n' "$RED"
  exit 1
fi
