# Original stability failure

The original repeat run is RED, interrupted before completing. It is not represented as a successful or skipped run. The first failure was repetition 16 (directory repeat15): Execution remained Loading in `settled()`, with `aria-busy=true`. The original saved stdout excerpt records repetitions 1–15 passing and 16–46 failing. That excerpt was read while the process was still running; it is not a complete final stdout or a final failure count.

`original-partial-stdout.txt` is the verbatim saved Read output. `original-read-provenance.json` records its source. `error-context.md` and `video.webm` are the first failure's original browser artifacts. The full original artifact directory remains retained outside git; the first failure and the recoverable original stdout are preserved here.

The initial claim that the command had not started was incorrect: the tool's interrupted/rejected response did not establish that. The artifacts and preserved stdout establish that the command ran and failed.

## Diagnosis

The auxiliary process launcher used `Popen(stdout=PIPE, stderr=STDOUT)` and stopped reading that pipe after the app's readiness line. HTTP logging eventually filled it and blocked request handlers. `stdout-pipe-diagnosis.json` records an executed probe: the undrained pipe stalled on request 561 at 65,520 of 65,536 bytes. Draining it restored HTTP 200 from the SAME server without a code change or restart. Redirecting server output to a file then passed 500 health requests.

The corrected stability launcher writes server output directly to a file, uses a separate reader for startup detection, and stops Playwright on the first failure. No test assertion, application timeout or test timeout was weakened. The production app and `scripts/ux-check.sh` required no logging change: the latter already writes server output to a file.

`../stability-green.txt` records the corrected run: all 60 cases (20 repetitions at each width) passed with the original assertions and worker count. `../stability-app.txt` preserves that app's output. The original RED result remains separate from the later GREEN result.
