# Simulation — vet receipt

**T2, two rounds, no open findings.** Boundary: `a2cb607..fa17385`, then the review-fix range
`fa17385..0a67586`. Both code-review calls requested medium; their result did not echo effort.
Final second-round corrections were checked inline and by failing-before regression tests.

| Round | Finding | Disposition / proof |
|---|---|---|
| 1 | P2 · missing Treasury hides run-owned paths | Fixed; cash-path metadata-unavailable test |
| 1 | P2 · reopened hidden graph stays 0×0 | Fixed; real graph hidden-scrub test and browser flow |
| 1 | P2 · policy Replay invisible | Fixed; visible legend assertion |
| 1 | P2 · lower curve lacks a hover/tap target | Fixed; full-height hour targets |
| 1 | P2 · evidence link neither scrolls nor focuses | Fixed; focus assertion in unit and browser tests |
| 1 | P3 · quadratic hour lookup per edge | Fixed; one intent-to-hour index, unchanged geometry checks |
| 1 | P3 · duplicated spoken cursor time | Fixed; aria-valuetext equals the single cursor description |
| 2 | P2 · scratch spec imports discovered specs | Scratch file removed, never committed; full UX collection verified |
| 2 | P2 · fallback mislabels another entity's account | Fixed; lender-only paths do not draw a Treasury chart |
| 2 | P2 · point time passed off as observation time | Fixed; missing as_of explicitly unavailable |
| 2 | P2 · empty base drops non-USD policy points | Fixed; currency comes from an available same-account point |
| 2 | P3 · reopening unchanged graph resets layout | Fixed; retained circle DOM identity assertion |

Ten correctness assertions failed before their fixes and passed afterward; the hour index is a
quality change. Summary: **11 applied (10 proven, 0 unproven), 1 recorded, 0 open**. Final checks:
333 unit tests; 101 UX cases, four viewport-specific skips; 12 judge-path/accessibility cases;
ruff, no_secrets, attribution and diff whitespace checks green. The exact match-simulation
acceptance command also passed after the last correction. Full merge gate belongs to the train.

Coverage: Scrubber, WorldMap, CashPaths, Simulation and their changed unit/e2e contracts, plus
brief/design alignment and screenshot QA. Security review was local: no new HIGH/MEDIUM issue;
token stays memory-only, export excludes it, and Vue text bindings remain escaped. Simplify's
four angles were checked inline under the solo restriction; the hour index and aria cleanup
overlapped code-review findings. No dependency, backend writer, schema or backfill change.
