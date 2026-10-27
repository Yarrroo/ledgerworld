# T27 README, architecture, schema, attribution — Close-out
> Close-out (/dev-close). Source: prp/2026-10-20-ledgerworld/briefs/T27.md (medium; design folded into the brief).
> Date: 2026-10-27

## What shipped
- `README.md` covers: What it is · Run the demo (fake mode, no keys) · Setup (sandbox key names,
  compose, tests) · Architecture · Honesty notes · Attribution · Licence.
- `docs/architecture.md` covers the system shape (mermaid, §4) with the credential boundary drawn
  as two roles, the credential table, the round order, the module map and the execution path with
  its leg-mode table.
- `docs/schema.md` covers Money, C1–C6 from `contracts/`, the C5 detail, the C6 route → `$defs`
  map, and the ledger, execution and job tables.
- `ATTRIBUTION.md` lists every added area, and `tests/test_skeleton.py` no longer has its own row.
- `docs/screenshots/{overview,treasury,lending}-fake.png` each carry the "Simulated provider"
  banner.

## Verification
- Accept: `uv run python checks/doc_has.py README.md "Run the demo" "Setup" "Architecture" "Attribution" "Licence" && uv run python checks/attribution.py`
  exits 0.
- `checks/no_secrets.py` passes. The first commit carried a literal demo token in the README, and
  round 1 replaced it with `$(openssl rand -hex 16)`.
- `uv run pytest -q tests/test_skeleton.py tests/demo`: 88 passed.
- I ran both documented paths:
  - `bash scripts/demo.sh --mode fake --out …` printed all 7 beats in 27 s, and
    `checks/demo_receipt.py` reported `ok`.
  - The `uv run bash deploy/entrypoint.sh` block served `/treasury` on :5001 with the fake banner
    and live data.
- Vet: T2 (331 changed lines, prose-only). The medium review found 6 doc-vs-code contradictions
  and all 6 were applied. The low review of the fix found nothing. Converged in 2 rounds with
  0 open.

## Docs updated
- This item is the docs.

## Follow-ups / known gaps
- The screenshots come from a local fake-mode server, not the public URL the brief names: no
  public deployment exists yet. Retake them once `LEDGERWORLD_URL` is live.
- There are no Simulation, Decisions or Execution screenshots. Those screens need a prepared run,
  which needs the job queue.
- (Resolved on main before the merge: `apiUrl` in `frontend/src/api/v1.js` now joins
  `VITE_API_BASE_URL=/` without producing `//api/v1/...`.)
- `deploy/Dockerfile` does not set `VITE_SOURCE_URL`, so the deployed footer has no AGPL §13 source
  link. The README says so.
