# Sandbox receipt as evidence — Close-out
> Close-out (/dev-close), board item 116. Date: 2026-10-28

## What shipped
- `docs/evidence/sandbox-receipt.json`: run `demo-20261027T190757Z-9674`, byte-identical to fb77903
  on `design/sandbox-receipt` (Mode B, scripted model, 3/3 checkpoints live). Not re-run or edited.
- `docs/evidence/README.md` labels it: date, API version 2024-09-27, sandbox, Mode B, scripted,
  the command-line demo store's run and not the public API's.
- `docs/submission.md` and `README.md` cite it instead of "no sandbox receipt is committed".
- Guard: `checks/tests/test_sandbox_evidence.py` (receipt passes `--require-live` through
  `demo_receipt.check`, carries no `no_secrets` pattern or host path, both docs cite it and no
  longer carry the retired sentence, whitespace-normalised since README wraps it).

## Verification
- `uv run python checks/demo_receipt.py docs/evidence/sandbox-receipt.json --require-live`: ok, 3/3.
- `pytest checks/tests/test_sandbox_evidence.py test_submission.py test_doc_claims.py
  test_submission_links.py`: 116 passed. Fails before: the retired-sentence test failed against
  the old README and submission.md; the leak test failed against a planted key and host path.
- ruff, `checks/no_secrets.py`, `checks/attribution.py`: ok. Full `checks/merge.sh` is the train's.

## Follow-ups / known gaps
- `checks/submission.py` reports `missing: links` on this tree and on the base commit alike; it is
  not this item's (the Links section lacks the public URLs).
- `prp/2026-10-28-doc-claims/close-out.md` keeps its dated note that the sentence stayed until a
  receipt landed; it is history, not a claim.
