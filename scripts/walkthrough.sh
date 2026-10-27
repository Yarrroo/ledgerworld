#!/usr/bin/env bash
# The walkthrough rehearsal (goal g5): drive the deployed app through the seven timed beats of
# docs/video-script.md in real time, captioned, and record it as a silent, labelled video.
#
#   bash scripts/walkthrough.sh URL       record a rehearsal of the deployment at URL (~4:35)
#   bash scripts/walkthrough.sh --dry-run build and validate the plan and subtitles; no browser
#
# Builds the plan and an SRT with scripts/walkthrough_plan.py, installs the e2e dependencies and
# chromium when missing, runs e2e/walkthrough.spec.ts with video on into a fresh mktemp directory,
# then prints the webm and SRT paths and a per-beat planned-vs-actual table. The directory is kept:
# it holds the recording. Exit 0 only when every beat's screen loaded and nothing was written.
# Anonymous and read-only: the spec aborts any write.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
e2e="$root/e2e"

usage() { echo "usage: bash scripts/walkthrough.sh URL | --dry-run" >&2; exit 2; }

url="" dry=0
while (($#)); do
  case "$1" in
    --dry-run) dry=1; shift ;;
    -h | --help | -*) usage ;;
    *) [[ -z "$url" ]] || usage; url="$1"; shift ;;
  esac
done
((dry)) || [[ "$url" =~ ^https?:// ]] || { echo "walkthrough: a URL (http or https) is required" >&2; usage; }

out="$(mktemp -d "${TMPDIR:-/tmp}/walkthrough.XXXXXX")"
fail() { echo "walkthrough: $1; output kept in $out" >&2; exit 1; }

(cd "$root" && uv run python scripts/walkthrough_plan.py --json "$out/plan.json" --srt "$out/walkthrough.srt") \
  || fail "the plan could not be built from docs/video-script.md"

# the table: planned window, and with a beats.json beside it, when each screen was ready and left
table() {
  node -e '
    const fs = require("fs"), [plan, beats] = process.argv.slice(1)
    const t = (s) => {
      if (s == null) return "  -  "
      const d = Math.round(s * 10)  // tenths, rounded once, so 59.96 reads 1:00.0, never 0:60.0
      return `${Math.floor(d / 600)}:${((d % 600) / 10).toFixed(1).padStart(4, "0")}`
    }
    const done = fs.existsSync(beats) ? JSON.parse(fs.readFileSync(beats, "utf-8")).beats : []
    console.log("beat     route         planned        ready    left     over   reached")
    for (const b of JSON.parse(fs.readFileSync(plan, "utf-8")).beats) {
      const r = done.find((d) => d.beat === b.beat)
      const over = r ? `${(r.left - b.end) >= 0 ? "+" : ""}${(r.left - b.end).toFixed(1)}s` : "-"
      console.log([b.beat.padEnd(8), b.route.padEnd(13), `${t(b.start)}-${t(b.end)}`.padEnd(14),
        t(r?.ready).padEnd(8), t(r?.left).padEnd(8), over.padEnd(6),
        r ? (r.reached ? "yes" : `NO ${r.error}`) : (done.length ? "not run" : "planned")].join(" "))
    }
  ' "$out/plan.json" "$out/beats.json"
}

if ((dry)); then
  [[ -f "$e2e/walkthrough.spec.ts" && -f "$e2e/walkthrough.config.ts" ]] || fail "the spec or its config is missing"
  if [[ -d "$e2e/node_modules/@playwright/test" ]]; then
    (cd "$e2e" && WALKTHROUGH_URL=http://localhost WALKTHROUGH_PLAN="$out/plan.json" WALKTHROUGH_OUT="$out" \
      npx --no-install playwright test --config walkthrough.config.ts --list >&2) || fail "the spec does not load"
  fi
  table
  rm -rf "$out"
  echo "walkthrough: dry run green" >&2
  exit 0
fi

if [[ ! -d "$e2e/node_modules/@playwright/test" ]]; then
  npm --prefix "$e2e" install --no-audit --no-fund --no-package-lock >&2 || fail "npm install failed"
fi
(cd "$e2e" && npx --no-install playwright install chromium >&2) || fail "chromium install failed"

(cd "$e2e" && WALKTHROUGH_URL="$url" WALKTHROUGH_PLAN="$out/plan.json" WALKTHROUGH_OUT="$out" \
  npx --no-install playwright test --config walkthrough.config.ts >&2)
status=$?

video="$(find "$out/artifacts" -name '*.webm' 2>/dev/null | head -n 1)"
table
echo "video: ${video:-none}"
echo "subtitles: $out/walkthrough.srt"
((status == 0)) && [[ -n "$video" ]] || fail "the rehearsal did not pass (playwright exit $status)"
