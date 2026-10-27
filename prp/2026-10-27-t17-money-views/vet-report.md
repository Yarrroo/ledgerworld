# Vet report: T17 screens

> /dev-vet on `03b060c..slot/ledgerworld-1`. Tier **T2**: the scan flagged three surfaces (the
> bearer header in `request()`, async reads, money formatting), across 16 files, about 2,080
> added lines (about 1,000 of them recorded JSON) and 6 subsystems, with tests present. Reading
> the hunks, money is display-only and T17 never sends the token, so this is not T3.
> Instruments: `/code-review medium`, `/simplify` (4 angles) and `/security-review`.

## Round 1

Security review: no findings at confidence ≥ 8. The diff it was given was this change's file set.

| # | Finding (source) | Grade | Outcome |
|---|---|---|---|
| 1 | P's terms subtract a committed reservation twice: as its outflow and again as its obligation (review) | high | applied; test fails before |
| 2 | Missed obligations are left out of P's terms (review) | high | applied; test fails before |
| 3 | An unknown floor (minor null) reads Floor kept (review) | high | applied; test fails before |
| 4 | The banner always says synthetic snapshot, even for a branch or a replay (review) | medium | applied; test fails before |
| 5 | `useReading` applies an older answer that arrives first; its context guard was dead code (review, 2 items deduped) | medium | applied; test fails before |
| 6 | `formatAmount` prints a rounded or exponent value for unsafe integers (review) | medium | applied; test fails before |
| 7 | `formatTime` throws on an unparseable time (review) | medium | applied; test fails before |
| 8 | Overview says "no run" while a refresh is in flight (own read) | low | applied; test fails before |
| 9 | The floor rule was written three times (review and simplify) | low | applied (`againstFloor`) |
| 10 | Lending reads `/overview` beside `/lending` (review) | low | recorded: contract gap, LendingResponse lists no pool accounts |
| 11–21 | Shell owns the notices, skeleton and Retry · `money`/`amountText` · `stateOf` · `isDue`/`byTime` in v1.js · one body guard in Overview · no-op assertions removed · `serveLending` helper · dead exports removed · one Intl formatter · shallow reading state · P's terms moved to `projectionTerms` (simplify) | low | applied (quality) |
| 22 | A `GatedAction` component (simplify) | low | recorded: two uses so far; worth extracting when T19 adds the third |
| 23 | A `MetricTile` component (simplify) | low | recorded: the template restructure isn't worth it before canonical mockups arrive |
| 24 | i18n is not used (simplify) | low | recorded: the product is English (system brief §15); noted in the v1.js header |
| 25 | Abort superseded requests (simplify) | low | recorded: the newest request wins and Refresh is disabled while busy |
| 26 | Compute the calculation lazily (simplify) | low | recorded: negligible at one account |
| 27 | A clock bound to the body for `hoursFrom` (simplify) | low | recorded: small gain, more indirection |

All eight correctness tests failed with the pre-fix sources restored (9 of 26 red; the ninth is
an older test that now reads a new hook). With the fixes: 26 of 26 pass, the build is clean and
the re-sweep is green.

## Round 2 (re-vet of the fix commit only, `/code-review medium 4e1eccf..slot/ledgerworld-1`)

| # | Finding | Grade | Outcome |
|---|---|---|---|
| 28 | A replay with no branch is labelled "Hypothetical branch" | medium | applied; test fails before |
| 29 | `againstFloor` treats a floor with no `minor` key as breached (NaN) | medium | applied; test fails before |
| 30 | A failed refresh leaves the "context changed" notice beside the error | medium | applied; test fails before |
| 31 | An owed obligation due after t is dropped from P's terms instead of named as excluded | medium | applied; test fails before |
| 32 | `floor` in Treasury's view model shadowed the API field | low | applied (renamed `floorCheck`) |
| 33 | The header implied `latestOnly` guards the reading screens | low | applied (header says it is for a polled resource the user selects) |
| 34 | Lending kept a `body` wrapper the other views dropped | low | applied |
| 35 | The browser decides floor kept or breached per account from the API's points | low | recorded: the comparison uses API figures only; the root fix is for the API to serve `floor_check` per account (follow-up for T16) |

Round 2 tests: all four failed against the round 1 code (4 of 30 red) and pass with the fixes
(30 of 30). Accept command exit 0; contract tests 71 passed; `attribution` and `no_secrets` ok.
The loop stopped at the cap of 2 rounds with nothing open.

**vet: T2, round 2, 27 applied (12 proven, 0 unproven), 8 recorded**
Coverage: read every frontend file in the diff, including its deletions (one brace), and the
backend `views.py`, `store.py` and `spendability.py` to check P's rule. The security review read
v1.js, the three views, the router and the package diff. The prose under `prp/` and the recorded
JSON examples were not read for correctness (the contract test validates the JSON).
