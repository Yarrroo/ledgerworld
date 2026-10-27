# Doc claims sweep — close-out

**Broke:** README.md, docs/submission.md and docs/architecture.md told readers the Airwallex
connector has no deposit lookup. That stopped being true when the connector gained
`find_deposit` (exact reference, every page read) and `wait_for_deposit` (at most ten reads one
second apart, terminal status only), used by `backend/app/execution/gateway.py` `find`/`get_object`.

**Why:** the deposit-settlement change touched code and tests, not the three docs.

**Fix:** the Mode B paragraph in each doc now says the deposit is found by reference and waited
on, and only a deposit still pending or unreadable after the wait stays an operator incident.
architecture.md keeps the orphan sweep's skip of deposits and now gives the real reason (no
`request_id` to tell ours from anyone else's).

**Swept, still true:** PostgreSQL storage (README, architecture), prepared-demo wording
(submission), orphan sweep behaviour (reconcile.py skips deposits). The sentence "no sandbox
receipt is committed" is left as is: it is still true until a live receipt is committed.

**Guard:** `checks/tests/test_doc_claims.py` fails if a retired claim reappears in any of the
three docs, or if a doc stops naming `find_deposit`/`wait_for_deposit` or either method leaves
the client.

**Verification:** `uv run pytest -q checks/tests/test_doc_claims.py checks/tests/test_submission.py`
80 passed (7 failed before the doc fix); ruff, `checks/no_secrets.py`, `checks/attribution.py` clean.
The full `bash checks/merge.sh` runs on the landing train, not in this slot. Repo-wide grep finds no
other copy of the retired claim.

**Not done here:** board item 116 (commit a live sandbox receipt) is parked: this run had no
Airwallex sandbox credentials, and a receipt cannot be produced without a real run.
