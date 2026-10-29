#!/usr/bin/env bash
# The judge path (goal g4): a cold browser walks Overview -> Simulation -> Decisions ->
# Execution in four clicks and opens a reconciled receipt, under the limit.
#
#   bash scripts/judge-path.sh URL [--max-seconds 60]
#
# Installs the e2e dependencies and chromium when missing (not timed), runs e2e/judge-path.spec.ts
# at every viewport x theme of the judge-path fixture, and prints, as its last line, the maximum
# elapsed seconds over those runs: 999 when any run or assertion failed. Exit 0 only when every
# run passed within the limit. Playwright's own output goes to stderr; stdout carries the number,
# which checks/goals/g4.py reads. Anonymous and read-only: the spec aborts any write.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
e2e="$root/e2e"

usage() { echo "usage: bash scripts/judge-path.sh URL [--max-seconds N]" >&2; echo "judge_path_s 999"; exit 2; }

url="" max=60
while (($#)); do
  case "$1" in
    --max-seconds) [[ $# -ge 2 && "$2" =~ ^[0-9]+([.][0-9]+)?$ ]] || usage; max="$2"; shift 2 ;;
    -h | --help) usage ;;
    -*) usage ;;
    *) [[ -z "$url" ]] || usage; url="$1"; shift ;;
  esac
done
[[ "$url" =~ ^https?:// ]] || { echo "judge-path: a URL (http or https) is required" >&2; usage; }

# a failed run keeps its output (failure screenshots) and names where; a passing one removes it
out="$(mktemp -d "${TMPDIR:-/tmp}/judge-path.XXXXXX")"
fail() { echo "judge-path: $1; output kept in $out" >&2; echo "judge_path_s 999"; exit 1; }

# dependencies and the browser: outside the timed window
if [[ ! -d "$e2e/node_modules/@playwright/test" ]]; then
  npm --prefix "$e2e" install --no-audit --no-fund --no-package-lock >&2 || fail "npm install failed"
fi
(cd "$e2e" && npx --no-install playwright install chromium >&2) || fail "chromium install failed"

expected="$(node -e '
  const j = require(process.argv[1]); console.log(j.viewports.length * j.themes.length)
' "$root/prp/2026-10-20-ledgerworld/design/modules/ui/fixtures/judge-path.json")" || fail "fixture unreadable"

(cd "$e2e" && JUDGE_PATH_URL="$url" JUDGE_PATH_OUT="$out" npx --no-install playwright test \
  --config playwright.config.ts >&2)
status=$?

seconds="$(node -e '
  const fs = require("fs"), path = require("path"), dir = process.argv[1]
  const runs = fs.readdirSync(dir).filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8")))
  for (const r of runs) console.error(`judge-path: ${r.project} ${r.seconds.toFixed(1)} s`)
  console.log(runs.length === Number(process.argv[2]) ? Math.max(...runs.map((r) => r.seconds)).toFixed(1) : "")
' "$out" "$expected")"

if ((status != 0)) || [[ -z "$seconds" ]]; then
  fail "a run failed (playwright exit $status; $(find "$out" -maxdepth 1 -name '*.json' | wc -l)/$expected timed runs passed)"
fi
rm -rf "$out"
echo "judge-path: slowest run ${seconds} s, limit ${max} s, ${expected} runs" >&2
echo "judge_path_s $seconds"
awk -v s="$seconds" -v m="$max" 'BEGIN { exit !(s <= m) }' || exit 1
