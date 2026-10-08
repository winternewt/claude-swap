#!/usr/bin/env bash
#
# claude-swap-redflag.sh — pre-upgrade supply-chain check for the `claude-swap`
# PyPI package. Run this BEFORE `uv tool upgrade claude-swap` to confirm a new
# release hasn't grown a phone-home path, a new network host, persistence, or
# obfuscation.
#
# What it does (no install, read-only):
#   1. Pulls every published artifact (wheel + sdist) from PyPI, verifies each
#      download's sha256 against PyPI's own metadata (detects a tampered CDN
#      object), and flags a yanked release.
#   2. Checks the artifacts' shape: nothing in the wheel outside the package and
#      its dist-info, no .pth startup hooks, entry points only into the package,
#      a stock sdist build backend with no build hooks or setup.py.
#   3. Lists every network host referenced in shipped code, marking each KNOWN
#      (Anthropic / PyPI) or *** NEW *** (anything else = red flag), and which
#      modules import network or subprocess machinery.
#   4. Surfaces exec/obfuscation and persistence (launchd/systemd/cron/shell rc)
#      constructs for eyeballing.
#   5. Diffs the code and the runtime dependencies against a baseline version
#      (default: the version you currently have installed) — new files included —
#      so you only re-read what changed.
#   6. Optionally confirms the published artifact == a local git checkout.
#
# Exit code 0 = nothing alarming; 1 = at least one red flag (NEW host, new
# risky construct or dependency vs baseline, odd artifact shape, sha mismatch,
# or a check that could not run); 2 = bad usage / missing tool. Always read the
# output — a clean exit is "no known-bad pattern", not a proof of safety.
#
# Usage:
#   ./claude-swap-redflag.sh                       # check latest stable vs installed
#   ./claude-swap-redflag.sh 0.16.0                # check a specific version
#   ./claude-swap-redflag.sh 0.16.0 --baseline 0.15.0b1
#   ./claude-swap-redflag.sh 0.16.0 --repo /data/sources/claude-swap
#   ./claude-swap-redflag.sh 0.16.0 --repo . --git-ref 9f62506   # vs a commit,
#       not the working tree — use this when the tree has moved past the release.
#       The repo publishes no tags; see SECURITY_AUDIT.md for finding the commit.
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

# The sdist build backend we expect. Anything else runs unknown code at
# `pip install` time from the sdist, before any of the code checks matter.
EXPECTED_BACKEND="hatchling.build"

# Constructs that matter in a delta. Matched case-insensitively against ADDED
# (and, informationally, REMOVED) lines; comment-only lines are dropped, lines
# with a trailing comment are kept.
RISKY_RE='urllib|requests|httpx|aiohttp|socket|http\.client|urlopen|smtplib|ftplib|webbrowser'
RISKY_RE+='|subprocess|os\.system|popen|os\.exec|os\.spawn|\bpty\b|\beval\(|\bexec\(|(^|[^.[:alnum:]_])compile\('
RISKY_RE+='|__import__|importlib|ctypes|cffi|pickle|marshal|base64|b64decode|fromhex|codecs|zlib|lzma|bz2'
RISKY_RE+='|\benviron\b|getenv|https?://|shell[[:space:]]*=[[:space:]]*true'
RISKY_RE+='|launchctl|launchagents|runatload|keepalive|systemctl|crontab|schtasks|autostart'
RISKY_RE+='|\.bashrc|\.zshrc|\.profile|sitecustomize|\.pth\b'

# Exec/obfuscation constructs listed for review over the whole shipped tree.
CONSTRUCT_RE='\beval\(|\bexec\(|(^|[^.[:alnum:]_])compile\(|os\.system|popen|os\.exec|os\.spawn|__import__|importlib'
CONSTRUCT_RE+='|ctypes|pickle|marshal|base64|fromhex|codecs\.decode|zlib|lzma|shell[[:space:]]*=[[:space:]]*True'

# Persistence: anything that would make code run without the user starting it.
PERSIST_RE='launchctl|LaunchAgents|LaunchDaemons|RunAtLoad|KeepAlive|systemctl|systemd|crontab'
PERSIST_RE+='|schtasks|autostart|\.bashrc|\.zshrc|\.profile|sitecustomize|\.pth\b|login item'

VERSION=""
BASELINE=""
REPO=""
GITREF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --baseline) BASELINE="$2"; shift 2 ;;
    --repo)     REPO="$2"; shift 2 ;;
    --git-ref)  GITREF="$2"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          VERSION="$1"; shift ;;
  esac
done

for bin in curl python3 sha256sum tar unzip diff comm git; do
  command -v "$bin" >/dev/null || { echo "missing required tool: $bin" >&2; exit 2; }
done

# Validate --repo/--git-ref up front: a typo here used to skip the comparison
# silently, which reads exactly like "nothing to report".
if [ -n "$GITREF" ] && [ -z "$REPO" ]; then
  echo "--git-ref needs --repo" >&2; exit 2
fi
if [ -n "$REPO" ]; then
  git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 \
    || { echo "--repo $REPO is not a git checkout" >&2; exit 2; }
  if [ -n "$GITREF" ]; then
    git -C "$REPO" rev-parse --verify --quiet "$GITREF^{commit}" >/dev/null \
      || { echo "--git-ref $GITREF does not name a commit in $REPO" >&2; exit 2; }
  fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
RED=0   # red-flag counter

note()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
flag()  { printf '  \033[31m*** RED FLAG: %s ***\033[0m\n' "$*"; RED=$((RED+1)); }
ok()    { printf '  \033[32m%s\033[0m\n' "$*"; }

curl -fsS --max-time 30 "$PYPI" -o "$WORK/meta.json"

# Resolve target version (default: latest non-prerelease) and baseline (default:
# currently-installed, if cswap is on PATH).
if [ -z "$VERSION" ]; then
  VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["info"]["version"])' "$WORK/meta.json")"
fi
if [ -z "$BASELINE" ] && command -v cswap >/dev/null 2>&1; then
  BASELINE="$(cswap --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+[0-9a-z.]*' | head -1 || true)"
fi

note "Target: ${PKG} ${VERSION}   Baseline: ${BASELINE:-<none>}"

# --- Download + integrity-verify one version's artifacts. Each artifact is
# extracted into its own directory (<filename>.d) so a second wheel cannot
# overwrite the first one's files and hide them from every later check.
fetch_and_extract() {
  local ver="$1" outdir="$WORK/$1"
  mkdir -p "$outdir"
  python3 - "$WORK/meta.json" "$ver" <<'PY' > "$WORK/files.$ver" || { echo "version $ver not on PyPI" >&2; return 3; }
import json,sys
d=json.load(open(sys.argv[1])); v=sys.argv[2]
rel=d["releases"].get(v)
if not rel: sys.exit(1)
for f in rel:
    print(f["filename"], f["digests"]["sha256"], bool(f.get("yanked")), f["url"])
PY
  while read -r fname sha yanked url; do
    curl -fsS --max-time 120 -o "$outdir/$fname" "$url"
    actual="$(sha256sum "$outdir/$fname" | cut -d' ' -f1)"
    if [ "$actual" != "$sha" ]; then
      flag "$fname sha256 MISMATCH vs PyPI metadata (download != published!)"
    else
      echo "  $fname  sha256 $actual"
    fi
    if [ "$yanked" = "True" ] && [ "$ver" = "$VERSION" ]; then
      flag "$fname is YANKED on PyPI — find out why before installing it"
    fi
    mkdir -p "$outdir/$fname.d"
    case "$fname" in
      *.whl)    ( cd "$outdir/$fname.d" && unzip -oq "$outdir/$fname" ) ;;
      *.tar.gz) tar xzf "$outdir/$fname" -C "$outdir/$fname.d" ;;
      *)        flag "unexpected artifact type on PyPI: $fname" ;;
    esac
  done < "$WORK/files.$ver"
}

# The package directory inside one extracted artifact, or nothing. Never use
# `dirname "$(find ... | head -1)"` for this: dirname of an empty string is
# ".", which silently points every later check at the current directory.
pkg_in() {
  local init
  init="$(find "$1" -path "*/$DIST/__init__.py" -not -path '*/tests/*' | sort | head -1)"
  if [ -n "$init" ]; then dirname "$init"; fi
}

wheels_of()  { find "$WORK/$1" -maxdepth 1 -type d -name '*.whl.d' | sort; }
sdists_of()  { find "$WORK/$1" -maxdepth 1 -type d -name '*.tar.gz.d' | sort; }

note "Downloading + verifying integrity"
fetch_and_extract "$VERSION"

mapfile -t TGT_WHEELS < <(wheels_of "$VERSION")
mapfile -t TGT_SDISTS < <(sdists_of "$VERSION")
[ ${#TGT_WHEELS[@]} -gt 1 ] && echo "  note: ${#TGT_WHEELS[@]} wheels — each is checked below"

# The wheel is what `uv tool install` installs; it is the primary subject of
# the code checks. Without one, fall back to the sdist's package.
TGT_PKG=""
if [ ${#TGT_WHEELS[@]} -gt 0 ]; then TGT_PKG="$(pkg_in "${TGT_WHEELS[0]}")"; fi
if [ -z "$TGT_PKG" ] && [ ${#TGT_SDISTS[@]} -gt 0 ]; then
  TGT_PKG="$(pkg_in "${TGT_SDISTS[0]}")"
  flag "no wheel for $VERSION — checking the sdist's package instead"
fi
[ -n "$TGT_PKG" ] || { echo "could not find the $DIST package in any artifact" >&2; exit 2; }

# Everything that can execute on install or import: every .py/.pth anywhere in
# any wheel (not only inside the package — a .pth or a stray top-level module
# runs too), plus the sdist's root-level .py files (setup.py, build hooks).
{
  for w in "${TGT_WHEELS[@]}"; do find "$w" -type f \( -name '*.py' -o -name '*.pth' \); done
  for s in "${TGT_SDISTS[@]}"; do find "$s" -mindepth 2 -maxdepth 2 -type f -name '*.py'; done
  if [ ${#TGT_WHEELS[@]} -eq 0 ]; then find "$TGT_PKG" -type f -name '*.py'; fi
} | sort -u > "$WORK/scan.list"
rel_path() { sed "s|$WORK/$VERSION/||"; }
scan_grep() {  # $1 = ERE; prints matching lines of the shipped code
  tr '\n' '\0' < "$WORK/scan.list" | xargs -0 grep -nE "$1" 2>/dev/null | rel_path || true
}

# --- 1) Artifact shape.
note "Artifact shape"
for w in "${TGT_WHEELS[@]}"; do
  wname="$(basename "$w" .d)"
  stray="$(find "$w" -mindepth 1 -maxdepth 1 ! -name "$DIST" ! -name "$DIST-$VERSION.dist-info")"
  if [ -n "$stray" ]; then
    echo "$stray" | sed "s|$w/|    |"
    flag "$wname ships top-level entries besides $DIST/ and its dist-info"
  fi
  pth="$(find "$w" -name '*.pth')"
  [ -z "$pth" ] || flag "$wname ships a .pth file (runs at every Python startup): $(echo "$pth" | sed "s|$w/||")"
  payload="$(find "$w/$DIST" -type f ! -name '*.py' ! -name '*.tcss' 2>/dev/null)"
  if [ -n "$payload" ]; then
    echo "$payload" | sed "s|$w/|    |"
    flag "$wname ships non-.py/.tcss files inside the package — inspect them"
  fi
  ep="$(find "$w" -path "*.dist-info/entry_points.txt" | head -1)"
  if [ -n "$ep" ]; then
    sed 's/^/    /' "$ep"
    if python3 - "$ep" "$DIST" <<'PY'; then
import configparser,sys
cp=configparser.ConfigParser(); cp.read(sys.argv[1]); pkg=sys.argv[2]
bad=[f"[{s}] {k} = {v}" for s in cp.sections() for k,v in cp[s].items()
     if s!="console_scripts" or not (v.startswith(pkg+".") or v.startswith(pkg+":"))]
for b in bad: print("    unexpected entry point:", b)
sys.exit(1 if bad else 0)
PY
      ok "$wname: entry points are console scripts into $DIST only"
    else
      flag "$wname: entry point outside console_scripts or outside $DIST"
    fi
  fi
  [ -z "$stray$pth$payload" ] && ok "$wname: only $DIST/ (.py + .tcss) and its dist-info; no .pth"
done
if [ ${#TGT_SDISTS[@]} -eq 0 ]; then
  flag "no sdist for $VERSION — wheel/sdist cross-check cannot run"
fi
for s in "${TGT_SDISTS[@]}"; do
  sname="$(basename "$s" .d)"
  root="$(find "$s" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if python3 - "$root/pyproject.toml" "$EXPECTED_BACKEND" <<'PY'; then
import sys
try:
    import tomllib
except ImportError:
    print("    python3 has no tomllib (needs 3.11+); cannot parse the build config"); sys.exit(1)
try:
    d=tomllib.load(open(sys.argv[1],"rb"))
except Exception as e:
    print(f"    cannot read sdist pyproject.toml: {e}"); sys.exit(1)
bs=d.get("build-system",{}); backend=bs.get("build-backend"); req=bs.get("requires",[])
print(f"    build-backend = {backend!r}, requires = {req!r}")
bad=backend!=sys.argv[2] or any(not r.strip().lower().startswith("hatchling") for r in req)
build=d.get("tool",{}).get("hatch",{}).get("build",{})
hooks=[]
if "hooks" in build: hooks.append("tool.hatch.build.hooks")
for t,cfg in build.get("targets",{}).items():
    if isinstance(cfg,dict) and "hooks" in cfg: hooks.append(f"tool.hatch.build.targets.{t}.hooks")
for h in hooks: print(f"    build hook configured: {h}")
sys.exit(1 if bad or hooks else 0)
PY
    ok "$sname: stock $EXPECTED_BACKEND backend, no build hooks"
  else
    flag "$sname: unexpected build backend or build hooks — this code runs at sdist install time"
  fi
  rootpy="$(find "$root" -maxdepth 1 -type f -name '*.py')"
  [ -z "$rootpy" ] || flag "$sname: root-level .py in sdist (setup.py / build hook): $(echo "$rootpy" | sed "s|$root/||" | tr '\n' ' ')"
done

# --- 2) Network hosts.
note "Network hosts referenced in shipped code"
python3 - "$WORK/scan.list" "$WORK/$VERSION/" "${KNOWN_HOSTS[@]}" <<'PY' > "$WORK/hosts.txt"
import re,sys
paths=[p for p in open(sys.argv[1]).read().splitlines() if p]
prefix=sys.argv[2]; known=set(sys.argv[3:])
hosts={}
for p in paths:
    text=open(p,encoding="utf-8",errors="replace").read()
    for m in re.finditer(r'https?://([^/\s"\'\\)]+)', text):
        h=m.group(1).rsplit("@",1)[-1]          # drop user:pass@
        if not h.startswith("["): h=h.split(":",1)[0]   # drop :port
        hosts.setdefault(h.lower(), set()).add(p.removeprefix(prefix))
for h in sorted(hosts):
    tag="KNOWN" if h in known else "NEW"
    print(f"{tag}\t{h}\t{','.join(sorted(hosts[h]))}")
PY
while IFS=$'\t' read -r tag host files; do
  if [ "$tag" = "NEW" ]; then flag "unknown network host: $host  (in $files)"
  else ok "KNOWN  $host  ($files)"; fi
done < "$WORK/hosts.txt"
echo "  (only literal scheme://host URLs are seen; a host built at runtime is not —"
echo "   which is why the module lists below matter)"

# --- 3) Which modules can talk to the network or spawn processes. These are
# the audit's load-bearing claims; a module joining either list needs a read.
note "Modules importing network / process machinery"
echo "  network (urllib, socket, http.client, ssl, requests, httpx, aiohttp, smtplib, ftplib):"
scan_grep '^[[:space:]]*(import|from)[[:space:]]+(urllib|socket|http\.client|http\b|ssl|requests|httpx|aiohttp|smtplib|ftplib)\b' \
  | cut -d: -f1 | sort -u | sed 's/^/    /'
echo "  processes (subprocess, os.system/popen/exec*/spawn*, pty):"
scan_grep 'import[[:space:]]+subprocess|from[[:space:]]+subprocess|os\.(system|popen|exec[lv]p?e?|spawn[lv]p?e?)\(|import[[:space:]]+pty' \
  | cut -d: -f1 | sort -u | sed 's/^/    /'

# --- 4) Sensitive constructs (informational — eyeball these).
note "Exec / obfuscation constructs (for review, not auto-failed)"
scan_grep "$CONSTRUCT_RE" > "$WORK/constructs.txt"
if [ -s "$WORK/constructs.txt" ]; then
  sed 's/^/  /' "$WORK/constructs.txt"
  echo "  (note: base64 in credentials.py is local .enc backup encoding — expected)"
else
  ok "no eval/exec/compile/os.system/pickle/ctypes/shell=True found"
fi

note "Persistence constructs (for review, not auto-failed)"
scan_grep "$PERSIST_RE" > "$WORK/persist.txt"
if [ -s "$WORK/persist.txt" ]; then
  sed 's/^/  /' "$WORK/persist.txt"
  echo "  (anything that writes these must be an explicit, user-invoked command — read the call sites)"
else
  ok "no launchd/systemd/cron/schtasks/shell-rc/.pth constructs found"
fi

# --- 5) Delta vs baseline: only re-read what changed, flag new risky lines.
requires_of() {  # $1 = extracted wheel dir; prints sorted Requires-Dist lines
  local md
  md="$(find "$1" -path '*.dist-info/METADATA' | head -1)"
  if [ -n "$md" ]; then grep -E '^Requires-Dist:' "$md" | sort; fi
}
if [ -z "$BASELINE" ]; then
  note "Delta vs baseline"
  flag "no baseline (cswap not on PATH and no --baseline): code and dependency deltas did NOT run"
elif [ "$BASELINE" = "$VERSION" ]; then
  note "Delta vs baseline"
  echo "  baseline equals target; nothing to diff"
else
  note "Security-relevant delta  ${BASELINE} -> ${VERSION}"
  BASE_PKG=""; BASE_WHEELS=()
  echo "  baseline artifacts:"
  if fetch_and_extract "$BASELINE"; then
    mapfile -t BASE_WHEELS < <(wheels_of "$BASELINE")
    if [ ${#BASE_WHEELS[@]} -gt 0 ]; then BASE_PKG="$(pkg_in "${BASE_WHEELS[0]}")"; fi
    if [ -z "$BASE_PKG" ]; then
      mapfile -t BASE_SDISTS < <(sdists_of "$BASELINE")
      [ ${#BASE_SDISTS[@]} -eq 0 ] || BASE_PKG="$(pkg_in "${BASE_SDISTS[0]}")"
    fi
  fi
  if [ -z "$BASE_PKG" ]; then
    flag "baseline $BASELINE not retrievable — code and dependency deltas did NOT run"
  else
    ( cd "$BASE_PKG" && find . -type f | sort ) > "$WORK/base.files"
    ( cd "$TGT_PKG"  && find . -type f | sort ) > "$WORK/tgt.files"
    added="$(comm -13 "$WORK/base.files" "$WORK/tgt.files")"
    removed="$(comm -23 "$WORK/base.files" "$WORK/tgt.files")"
    [ -z "$added" ]   || { echo "  New files (read these in full — every line below counts as added):"; echo "$added" | sed 's|^\./|    + |'; }
    [ -z "$removed" ] || { echo "  Removed files:"; echo "$removed" | sed 's|^\./|    - |'; }

    # -N treats a missing file as empty, so a brand-new module's lines show
    # up as additions instead of a bare "Only in" that nothing scans.
    diff -rN "$BASE_PKG" "$TGT_PKG" > "$WORK/delta.diff" 2>/dev/null || true
    if [ ! -s "$WORK/delta.diff" ]; then
      ok "no code differences between $BASELINE and $VERSION"
    else
      echo "  Changed files:"
      grep -E '^diff ' "$WORK/delta.diff" | sed "s|.* $TGT_PKG/|    |" || true
      if grep -E '^> ' "$WORK/delta.diff" | grep -vE '^>[[:space:]]*#' \
           | grep -iE "$RISKY_RE" > "$WORK/delta.risky"; then
        echo "  Added lines touching network/exec/env/obfuscation/persistence:"
        sed 's/^/    /' "$WORK/delta.risky"
        flag "delta introduces $(wc -l < "$WORK/delta.risky") line(s) touching risky constructs — review the lines above"
      else
        ok "delta adds NO network/exec/env/obfuscation/persistence code"
      fi
      if grep -E '^< ' "$WORK/delta.diff" | grep -vE '^<[[:space:]]*#' \
           | grep -iE "$RISKY_RE" > "$WORK/delta.removed"; then
        echo "  Removed lines touching the same constructs (check no guard was dropped):"
        sed 's/^/    /' "$WORK/delta.removed"
      fi
    fi

    # New dependencies are new code this script never reads.
    if [ ${#TGT_WHEELS[@]} -gt 0 ] && [ ${#BASE_WHEELS[@]} -gt 0 ]; then
      requires_of "${BASE_WHEELS[0]}" > "$WORK/base.req"
      requires_of "${TGT_WHEELS[0]}"  > "$WORK/tgt.req"
      if diff "$WORK/base.req" "$WORK/tgt.req" > "$WORK/req.diff"; then
        ok "runtime dependencies unchanged ($(wc -l < "$WORK/tgt.req") Requires-Dist lines)"
      else
        sed -n 's/^> /    + /p; s/^< /    - /p' "$WORK/req.diff"
        if grep -q '^> ' "$WORK/req.diff"; then
          flag "dependencies added or changed — their code is not covered by this script"
        fi
      fi
    else
      flag "could not compare dependencies (a wheel is missing)"
    fi
  fi
fi

# --- 6) Optional: published == local git checkout.
# Compares every file in the published package, not just top-level *.py — the
# package has subpackages (tui/) and non-.py assets (.tcss), and a top-level
# glob would silently skip a backdoor planted in any of them.
if [ -n "$REPO" ]; then
  if [ -n "$GITREF" ]; then
    note "Published $VERSION  vs  git ref $GITREF"
  else
    note "Published $VERSION  vs  local git working tree"
  fi
  mism=0; checked=0
  while read -r rel; do
    checked=$((checked+1))
    pub="$(sha256sum "$TGT_PKG/$rel" | cut -d' ' -f1)"
    if [ -n "$GITREF" ]; then
      # Test for the path first: under pipefail a failing `git show` inside
      # the substitution used to abort the whole script with no message.
      git -C "$REPO" cat-file -e "$GITREF:src/$DIST/$rel" 2>/dev/null \
        || { echo "  only-in-pypi: $rel"; mism=1; continue; }
      loc="$(git -C "$REPO" show "$GITREF:src/$DIST/$rel" | sha256sum | cut -d' ' -f1)"
    else
      [ -f "$REPO/src/$DIST/$rel" ] || { echo "  only-in-pypi: $rel"; mism=1; continue; }
      loc="$(sha256sum "$REPO/src/$DIST/$rel" | cut -d' ' -f1)"
    fi
    [ "$pub" = "$loc" ] || { echo "  DIFFERS: $rel"; mism=1; }
  done < <(cd "$TGT_PKG" && find . -type f | sed 's|^\./||' | sort)
  if [ $mism -eq 0 ]; then
    ok "published artifact == repo (all $checked files match)"
  else
    flag "published artifact differs from local repo (see above)"
    [ -z "$GITREF" ] && echo "  hint: if the tree has moved past the release, re-run with --git-ref <release-commit>"
  fi
fi

# --- 7) Wheel and sdist must ship identical code (both are installable paths).
note "Wheel vs sdist"
if [ ${#TGT_WHEELS[@]} -gt 0 ] && [ ${#TGT_SDISTS[@]} -gt 0 ]; then
  SDIST_PKG="$(pkg_in "${TGT_SDISTS[0]}")"
  for w in "${TGT_WHEELS[@]}"; do
    WPKG="$(pkg_in "$w")"
    if [ -z "$WPKG" ] || [ -z "$SDIST_PKG" ]; then
      flag "$(basename "$w" .d): could not locate the package in both artifacts"
    elif diff -r "$WPKG" "$SDIST_PKG" > "$WORK/whl_sdist.diff" 2>&1; then
      ok "$(basename "$w" .d) and sdist ship identical package code"
    else
      sed 's/^/    /' "$WORK/whl_sdist.diff"
      flag "$(basename "$w" .d) and sdist DIFFER — the two install paths deliver different code"
    fi
  done
else
  echo "  (skipped — reported under Artifact shape)"
fi

# --- Verdict.
note "Verdict"
if [ $RED -eq 0 ]; then
  printf '  \033[32mNo red flags: integrity verified, artifact shape as expected, no unknown hosts,\033[0m\n'
  printf '  \033[32mno new risky constructs or dependencies vs %s.\033[0m\n' "$BASELINE"
  echo   "  Read the review sections above, then: uv tool install '${PKG}==${VERSION}'"
  exit 0
else
  printf '  \033[31m%d red flag(s) — review above BEFORE upgrading.\033[0m\n' "$RED"
  exit 1
fi
