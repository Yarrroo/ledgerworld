# Decisions: a replayed comparison says Replay on the page — close-out
> Source: a review finding on design match 0 (the shared header). Date: 2026-10-30

## What shipped
- `frontend/src/api/v1.js`: one helper, `replayed(body)`, true when the body carries `replay` or any of
  its `results[]` does. The header's tag (`contextTag`), its second line (`dataKind`) and the Figures
  label (`sourceLabel`) read it instead of a top-level `body.replay` alone. A Decisions comparison
  carries replay per result, so before this a replayed comparison read "Synthetic data" and its Replay
  words sat only in tooltips.
- `frontend/src/views/Decisions.vue`: the How we know note uses the same helper.
- With any replayed result, the whole comparison is tagged Replay in the header (the rule the system
  brief sets: a precomputed cohort is labelled replay). Each row's own provenance stays in How we
  know and the details table.

## Verification
- Regression tests, red before the fix and green after: `frontend/tests/unit/copy-3.spec.js`
  (the helpers on a results-level replay), `frontend/tests/unit/decide-execute.spec.js` (the header
  says Replay outside every tooltip; a fresh comparison does not), and `e2e/ux/decisions.spec.ts`
  (the same at 1440, 834 and 390 px; red at all three before the fix).
- `vitest run`: 302 passed. `npm --prefix frontend run build`: green. `checks/attribution.py`,
  `checks/no_secrets.py`: ok.
- `bash scripts/ux-check.sh e2e/ux/decisions.spec.ts` and `… match-shared.spec.ts` (the original
  task's accept): green at 1440, 834 and 390 px, each followed by a green judge path.
- The full pytest suite is the landing train's and was not run here.

## Docs updated
- None beyond this file: the brief already requires visible replay status (`00-system.md`, honesty labels).

## Follow-ups / known gaps
- None found.
