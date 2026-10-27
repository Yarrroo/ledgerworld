# T26 judge path in a real browser — Close-out
> Close-out (/dev-close). Source: prp/2026-10-20-ledgerworld/briefs/T26.md ← design/modules/ui/HANDOFF.md.
> Date: 2026-10-27

## What shipped
- `scripts/judge-path.sh URL [--max-seconds 60]`: installs `e2e/` deps and chromium when missing
  (not timed), runs the spec at every viewport × theme of `fixtures/judge-path.json`
  (390/1280/1440 px, light and dark), prints `judge_path_s <slowest seconds>` as its last stdout
  line (999 on any failure; `checks/goals/g4.py` reads it), exits 0 only within the limit. A
  failed run keeps its output dir (screenshots) and names it.
- `e2e/judge-path.spec.ts`: per project, a **timed** test (Overview → Open simulation → Compare
  policies → View execution → Open receipt on the deployment's prepared `demo` run/execution) and
  an untimed **accessibility** test (same clicks plus Treasury and Lending, reduced motion on:
  overflow, status text, 44 px controls at 390 px, rendered contrast, keyboard focus visible).
  Every non-GET request is aborted and fails the run.
- `e2e/playwright.config.ts`, `e2e/package.json` (`@playwright/test` 1.64.1, pinned; new
  dependency, test-only).

## Verification
- Local stand-in (API on fakes with a run, a fork, an approved and reconciled fake execution,
  `prepare_demo`, built frontend at `VITE_API_BASE_URL=/`): 12/12 passed, `judge_path_s 2.3`,
  exit 0; `--max-seconds 0.5` printed the seconds and exited 1; an unreachable URL printed 999,
  exit 1; `LEDGERWORLD_URL=<stand-in> python3 checks/kpi.py g4` printed `g4 judge_path_s 1.1`.
  The stand-in forced the scripted decision to `selected` (the scripted world's fork at round 2
  reads `all_infeasible`), so it proves the script, not the deployment's data.
- Public URL (`deploy/host.toml`): Overview loads, every run fails at
  "the deployment names no prepared demonstration run" (`demo.run_id` null) → 999, exit 1. This
  is the honest failure the brief asks for; the accept cannot pass until the deployment prepares one.
- `checks/no_secrets.py` ok, `checks/attribution.py` ok; ruff has no Python in `e2e/`.
- Vet: T2 (429 added lines), 2 rounds, 7 applied, 3 recorded, 0 open.

## Docs updated
- None outside the owned files: the wrapper and spec carry their own usage headers.

## Follow-ups / known gaps
- **Blocks the accept:** nothing calls `Services.prepare_demo` (no route, no CLI), and
  `scripts/demo.sh` executes in its own store, not the API's. The deployment needs a warm step
  that runs a demo run + fork, approves and executes the selected plan through the API's store,
  and names it (T25 "warm the demo world").
- On the scripted world the round-2 fork reads `all_infeasible`, so no plan can be approved from
  the API's own flow; Decisions would show no surviving plan.
- Once the demo execution pays the payroll, Overview has no open obligation and shows "No open
  obligation" instead of the payroll deadline; the spec accepts that wording.
- Recorded vet findings: a path-prefixed deployment URL is unsupported (deploys at root); GETs
  pass through the write-blocking route (cost measured ~ms, kept for read-only by construction);
  contrast over background images/gradients is not measured.
