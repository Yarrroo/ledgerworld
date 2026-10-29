#!/usr/bin/env bash
# The narrated machine take (goal g5): a voiced, labelled walkthrough of the deployed app in one
# MP4, for upload when no human take exists. It publishes nothing and leaves docs/submission.md alone.
#
#   bash scripts/narrated_take.sh URL       record the take of the deployment at URL (~4:40)
#   bash scripts/narrated_take.sh --dry-run build the plan, estimate the voice fit, print the card
#                                           and the mux command; offline, no browser, no voice
#
# A take runs checks/recording_ready.py URL first and stops unless it prints GO. Then it voices the
# seven Voice lines (scripts/voiceover.py, edge-tts), records e2e/narrated-take.spec.ts (a 3-second
# card naming the voice as synthetic, then the beats in real time), and lays each clip over its
# beat's actual start with ffmpeg (imageio-ffmpeg). Both tools are fetched by uv for the call only.
# With LEDGERWORLD_DEMO_TOKEN in the environment the spec sends the script's operator actions
# (fresh fork, approval request, interview) off-screen; without it the take is read-only and says so.
# The token is never printed, passed on a command line or written to the output directory.
# Prints the MP4's path, size and sha256 and a per-beat table; the mktemp directory is kept.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
e2e="$root/e2e"
tts=(--with edge-tts==7.3.1 --with imageio-ffmpeg==0.7.0)

usage() { echo "usage: bash scripts/narrated_take.sh URL | --dry-run" >&2; exit 2; }

url="" dry=0
while (($#)); do
  case "$1" in
    --dry-run) dry=1; shift ;;
    -h | --help | -*) usage ;;
    *) [[ -z "$url" ]] || usage; url="$1"; shift ;;
  esac
done
((dry)) || [[ "$url" =~ ^https?:// ]] || { echo "narrated-take: a URL (http or https) is required" >&2; usage; }

out="$(mktemp -d "${TMPDIR:-/tmp}/narrated-take.XXXXXX")"
fail() { echo "narrated-take: $1; output kept in $out" >&2; exit 1; }
voiceover() { (cd "$root" && uv run "$@"); }

if ((dry)); then
  [[ -f "$e2e/narrated-take.spec.ts" && -f "$e2e/narrated-take.config.ts" ]] || fail "the spec or its config is missing"
  voiceover python scripts/walkthrough_plan.py --json "$out/plan.json" --srt "$out/take.srt" \
    || fail "the plan could not be built from docs/video-script.md"
  voiceover python scripts/voiceover.py voice --out "$out/voice" --dry-run || fail "a Voice line cannot fit its beat"
  voiceover python scripts/voiceover.py label --operator >"$out/label.json" || fail "the opening card could not be built"
  cat "$out/label.json" >&2
  # the mux, as it would run over a take that kept to plan
  node -e '
    const fs = require("fs"), [plan, beats] = process.argv.slice(1)
    const b = JSON.parse(fs.readFileSync(plan, "utf-8")).beats
    fs.writeFileSync(beats, JSON.stringify({ offset: 3, beats: b.map((x) => ({ beat: x.beat, began: x.start })) }))
  ' "$out/plan.json" "$out/beats.json" || fail "the planned placement could not be written"
  voiceover python scripts/voiceover.py mux --dry-run --video "$out/take.webm" --voice "$out/voice/voice.json" \
    --beats "$out/beats.json" --out "$out/take.mp4" >&2 || fail "the mux command could not be built"
  if [[ -d "$e2e/node_modules/@playwright/test" ]]; then
    (cd "$e2e" && NARRATED_URL=http://localhost NARRATED_PLAN="$out/plan.json" NARRATED_OUT="$out" \
      NARRATED_LABEL="$out/label.json" npx --no-install playwright test --config narrated-take.config.ts --list >&2) \
      || fail "the spec does not load"
  fi
  rm -rf "$out"
  echo "narrated-take: dry run green" >&2
  exit 0
fi

(cd "$root" && uv run python checks/recording_ready.py "$url") || fail "the deployment is not ready to record (no GO)"

voiceover python scripts/walkthrough_plan.py --json "$out/plan.json" --srt "$out/take.srt" \
  || fail "the plan could not be built from docs/video-script.md"
voiceover "${tts[@]}" python scripts/voiceover.py voice --out "$out/voice" || fail "the voice could not be built"
operator=()
[[ -n "${LEDGERWORLD_DEMO_TOKEN:-}" ]] && operator=(--operator)
[[ ${#operator[@]} -gt 0 ]] || echo "narrated-take: LEDGERWORLD_DEMO_TOKEN is not set; the take is read-only" >&2
voiceover python scripts/voiceover.py label "${operator[@]}" >"$out/label.json" || fail "the opening card could not be built"

if [[ ! -d "$e2e/node_modules/@playwright/test" ]]; then
  npm --prefix "$e2e" install --no-audit --no-fund --no-package-lock >&2 || fail "npm install failed"
fi
(cd "$e2e" && npx --no-install playwright install chromium >&2) || fail "chromium install failed"

(cd "$e2e" && NARRATED_URL="$url" NARRATED_PLAN="$out/plan.json" NARRATED_OUT="$out" NARRATED_LABEL="$out/label.json" \
  npx --no-install playwright test --config narrated-take.config.ts >&2)
status=$?

video="$(find "$out/artifacts" -name '*.webm' 2>/dev/null | head -n 1)"
[[ -f "$out/beats.json" ]] && voiceover python scripts/voiceover.py summary --voice "$out/voice/voice.json" --beats "$out/beats.json"
((status == 0)) && [[ -n "$video" ]] || fail "the take did not pass (playwright exit $status)"

voiceover "${tts[@]}" python scripts/voiceover.py mux --video "$video" --voice "$out/voice/voice.json" \
  --beats "$out/beats.json" --out "$out/ledgerworld-narrated-take.mp4" || fail "the mux failed"
take="$out/ledgerworld-narrated-take.mp4"
echo "take: $take"
echo "size: $(stat -c %s "$take") bytes"
echo "sha256: $(sha256sum "$take" | cut -d' ' -f1)"
echo "subtitles: $out/take.srt (planned times, without the card's 3 s)"
