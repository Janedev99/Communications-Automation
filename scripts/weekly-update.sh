#!/usr/bin/env bash
# weekly-update.sh — generate a weekly status update from git activity on pushed branches.
#
# Usage:
#   scripts/weekly-update.sh                       # last 7 days, all branches, print to stdout
#   scripts/weekly-update.sh --days 14             # change the window
#   scripts/weekly-update.sh --author "Rheynard"   # filter by author (default: current git user)
#   scripts/weekly-update.sh --all-authors         # include every author
#   scripts/weekly-update.sh --project "jane-autocomms"  # override project name
#   scripts/weekly-update.sh --sync                # also POST the update to PM-PRIME
#   scripts/weekly-update.sh --json                # emit machine-readable JSON instead of text
#
# Env:
#   PM_PRIME_URL    default: https://pm-prime-production.up.railway.app/api/webhooks/claude
#   PM_PRIME_TOKEN  required when --sync is used
#
# Notes:
#   - Reads commits from local refs AND remote-tracking refs (origin/*), so anything you've
#     pushed shows up even if your local branch is behind.
#   - Run `git fetch --all --prune` first if you want the freshest remote state.

set -euo pipefail

DAYS=7
AUTHOR=""
ALL_AUTHORS=0
PROJECT=""
SYNC=0
EMIT_JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --days)         DAYS="$2"; shift 2 ;;
    --author)       AUTHOR="$2"; shift 2 ;;
    --all-authors)  ALL_AUTHORS=1; shift ;;
    --project)      PROJECT="$2"; shift 2 ;;
    --sync)         SYNC=1; shift ;;
    --json)         EMIT_JSON=1; shift ;;
    -h|--help)
      sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ -z "$PROJECT" ]]; then
  PROJECT="$(basename "$repo_root")"
fi

if [[ "$ALL_AUTHORS" -eq 0 && -z "$AUTHOR" ]]; then
  AUTHOR="$(git config user.name || true)"
fi

since="$DAYS days ago"

# Pull commits from local + remote-tracking refs, dedupe by hash.
# Format: <hash>\t<date>\t<author>\t<subject>
mapfile -t commits < <(
  git log --all --remotes --since="$since" --no-merges \
    ${AUTHOR:+--author="$AUTHOR"} \
    --pretty=format:'%H%x09%ad%x09%an%x09%s' --date=short \
  | awk -F'\t' '!seen[$1]++'
)

# Branches with activity in the window (local + remote-tracking).
mapfile -t active_branches < <(
  git for-each-ref --sort=-committerdate \
    --format='%(committerdate:short)|%(refname:short)' \
    refs/heads refs/remotes/origin \
  | awk -F'|' -v cutoff="$(date -d "$since" +%Y-%m-%d 2>/dev/null || date -v-"${DAYS}"d +%Y-%m-%d)" \
      '$1 >= cutoff { print $2 }' \
  | grep -Ev '^(origin|origin/HEAD)$' \
  | sort -u
)

# --- Categorize commits by conventional-commit prefix ----------------------
completed=()  # feat / perf / refactor / docs / chore that landed
fixes=()      # fix
tests=()      # test
other=()

for line in "${commits[@]}"; do
  subject="${line##*$'\t'}"
  case "$subject" in
    feat*|Feat*|FEAT*)         completed+=("$subject") ;;
    fix*|Fix*|FIX*)            fixes+=("$subject") ;;
    test*|Test*|TEST*)         tests+=("$subject") ;;
    perf*|refactor*|docs*|chore*|Perf*|Refactor*|Docs*|Chore*)
                               completed+=("$subject") ;;
    *)                         other+=("$subject") ;;
  esac
done

total=${#commits[@]}
n_feat_like=${#completed[@]}
n_fix=${#fixes[@]}
n_test=${#tests[@]}

# --- Build the human-readable update ---------------------------------------
print_text_update() {
  echo "PROJECT STATUS"
  echo "Project: $PROJECT"
  echo "Window:  last $DAYS days  (since $(date -d "$since" +%Y-%m-%d 2>/dev/null || date -v-"${DAYS}"d +%Y-%m-%d))"
  if [[ "$ALL_AUTHORS" -eq 0 ]]; then
    echo "Author:  $AUTHOR"
  else
    echo "Author:  (all)"
  fi
  echo "Commits: $total  (feat/perf/refactor: $n_feat_like, fixes: $n_fix, tests: $n_test)"
  echo

  echo "ACTIVE BRANCHES"
  if [[ ${#active_branches[@]} -eq 0 ]]; then
    echo "  (none)"
  else
    for b in "${active_branches[@]}"; do echo "  - $b"; done
  fi
  echo

  echo "WORK COMPLETED"
  if [[ ${#completed[@]} -eq 0 && ${#fixes[@]} -eq 0 && ${#tests[@]} -eq 0 ]]; then
    echo "  (no commits in window)"
  else
    for s in "${completed[@]}"; do echo "  • $s"; done
    for s in "${fixes[@]}";     do echo "  • $s"; done
    for s in "${tests[@]}";     do echo "  • $s"; done
  fi

  if [[ ${#other[@]} -gt 0 ]]; then
    echo
    echo "OTHER COMMITS"
    for s in "${other[@]}"; do echo "  • $s"; done
  fi

  echo
  echo "CURRENT BLOCKERS"
  echo "No blockers at this time."
  echo
  echo "THIS WEEK'S PROJECT PLAN"
  echo "  • (fill in: planned work for the coming week)"
  echo
  echo "NEXT MILESTONE"
  echo "(fill in: next major milestone)"
}

# --- Build PM-PRIME JSON payload -------------------------------------------
# JSON-escape a single string for safe embedding.
json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n")))' 2>/dev/null \
  || node -e 'let s=""; process.stdin.on("data",d=>s+=d); process.stdin.on("end",()=>process.stdout.write(JSON.stringify(s.replace(/\n$/,""))))'
}

build_array() {
  # turn a bash array into a JSON array of {"title": "..."} objects
  local -n arr=$1
  local out="[" first=1
  for s in "${arr[@]}"; do
    local esc; esc="$(printf '%s' "$s" | json_escape)"
    if [[ $first -eq 1 ]]; then first=0; else out+=","; fi
    out+="{\"title\":$esc}"
  done
  out+="]"
  printf '%s' "$out"
}

build_payload() {
  local summary="Weekly update for ${PROJECT}: ${total} commits in last ${DAYS} days (${n_feat_like} feat/perf/refactor, ${n_fix} fixes, ${n_test} tests)."
  local summary_esc; summary_esc="$(printf '%s' "$summary" | json_escape)"
  local project_esc; project_esc="$(printf '%s' "$PROJECT" | json_escape)"

  local completed_all=("${completed[@]}" "${fixes[@]}" "${tests[@]}")
  local completed_json; completed_json="$(build_array completed_all)"

  cat <<EOF
{
  "action": "report",
  "projectName": $project_esc,
  "summary": $summary_esc,
  "completed": $completed_json,
  "inProgress": [],
  "todo": []
}
EOF
}

# --- Output ----------------------------------------------------------------
if [[ "$EMIT_JSON" -eq 1 ]]; then
  build_payload
else
  print_text_update
fi

# --- Optional sync to PM-PRIME --------------------------------------------
if [[ "$SYNC" -eq 1 ]]; then
  : "${PM_PRIME_URL:=https://pm-prime-production.up.railway.app/api/webhooks/claude}"
  if [[ -z "${PM_PRIME_TOKEN:-}" ]]; then
    echo >&2
    echo "ERROR: --sync requires PM_PRIME_TOKEN env var." >&2
    exit 1
  fi
  payload="$(build_payload)"
  echo >&2
  echo "Syncing to PM-PRIME at $PM_PRIME_URL ..." >&2
  curl -sS -X POST "$PM_PRIME_URL" \
    -H "Authorization: Bearer ${PM_PRIME_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$payload"
  echo >&2
fi
