# Execution panels E1–E6 and the approval dialog — Close-out
> Close-out (/dev-close). Source: design.md ← prp/2026-10-29-ux-pass/HANDOFF.md (board item 133).
> Date: 2026-10-29

## What shipped
- `frontend/src/views/Execution.vue`: panels E1 context · E2 approval review · E3 approval
  summary (copyable approval id) · E4 leg tracker (Ready → Submitted → Provider-confirmed →
  Reconciled, raw status, amount) expanding to E5 receipts · E6 incidents with evidence.
  Desktop: legs left, terms and incidents right; one column below 1200 px.
- One dialog, stage derived from the existing guards: review, submitting, unknown, approved,
  expired, executing, reconciled, incident. Execute stays a separate act; after it the dialog
  follows the polled execution (it used to close). Read status is a GET. Copy of id and hash
  announces politely. Escape/Tab handled on the document while open; focus returns to Review
  plan. Phone: full-height dialog, fixed action footer.
- `e2e/ux/execution.spec.ts` (new): every stage against a mocked API at 1440/834/390.
- `frontend/tests/unit/decide-execute.spec.js`: four tests that encoded the auto-close now
  close explicitly; 15 new cases (stages, copy, trap, and the nine vet-round-1 regressions).

## Verification
- Unit: `npx vitest run` in `frontend/`: 259 passed (13 files).
- Check line: `bash scripts/ux-check.sh e2e/ux/execution.spec.ts`: 15/15 at three widths,
  judge path 12/12, green (re-run after the vet fixes).
- `checks/no_secrets.py` ok · `checks/attribution.py` ok · ruff on `e2e checks` ok ·
  frontend build ok. The full `checks/merge.sh` (pytest) is the landing train's, not run here.
- Vet: T2, 2 rounds, 11 applied (9 with a fails-before test, 1 CSS fallback unproven, 1 doc),
  1 dismissed (Read status reads overlapping: `readNow` already returns while one is out), 0 open.
- Evidence screenshots: `ux/` (taken before the vet round), `ux-sweep.md`.

## Docs updated
- `design.md` brought in line with the vet's stage changes. No README/CLAUDE.md change: no
  command or workflow changed.

## Follow-ups / known gaps
- Leg source and dependencies (E4) are not in the C6 execution read; shown only in the dialog's
  bound terms. Showing them on the page needs an API field (HANDOFF "Panel projections").
- The 4xx-refused execute still needs a new review to retry (unchanged from before this item).
