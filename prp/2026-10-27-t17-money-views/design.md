# T17 · Overview, Treasury and Lending — build design

> Design output (dev-build stage 2, Large, architect shape). Source: `briefs/T17.md` and
> `design/modules/ui/HANDOFF.md` (the approved module design; this file records only the build
> decisions it leaves open). Next: implement → vet → close. No design page was pushed: the module
> design is the visual reference and this run has no reviewer to show one to.

## Requirements (accept, pre-registered)

- `npm --prefix frontend ci && npm --prefix frontend run build && npm --prefix frontend run test:unit -- tests/unit/money-views.spec.js` exits 0.
- `bash checks/merge.sh` exits 0.
- The spec loads `money-views.json` and `data-states.json` unchanged and asserts their expected text.

## Readers and writers (who else touches this)

| Party | Reads / writes | What it needs from T17 |
|---|---|---|
| Judge (anonymous) | reads `/overview` first, then `Open simulation` | answer strip at a glance, mode banner, no token |
| T18 Simulation, T19 Decisions/Execution | import `src/api/v1.js` | one client: context key, per-resource generation, money/time/status formatters, screen list, mode labels |
| T26 judge path | drives `/overview` → `/simulation?run_id=` | stable route paths and the CTA text `Open simulation` |
| API (T16, C6) | producer | the browser formats C6, never recomputes S, P or K_p |
| `contracts/examples/c6_api` | recorded responses | treasury, lending and the venue-freeze overview recorded from the API, validated by the contract test |

## Decisions

1. **Shared shell lives in `v1.js` + `tokens.css`, not a new component.** Each view renders the
   banner and nav from `SCREENS`, `modeLabel()` and the `.lw-*` classes. Keeps T17 inside its
   owned files; T18/T19 reuse the same helpers.
2. **Client is `fetch`, not the upstream axios instance** — the upstream instance retries on
   failure, and a financial POST must never retry. Reads only here; `request()` is exported for
   T19's writes.
3. **Late responses**: `latest()` stamps each request with a generation per resource and the
   context key `(mode, snapshot_id, run_id, branch_id)`; an older generation or a response whose
   context differs from the selected one is dropped.
4. **Metric text** in one function: `known` → `USD 70,000.00`, `stale` → `… · stale` plus as_of,
   `unknown` → `Unknown`, `unassessed` → `Not assessed`, never a zero for a null.
5. **Calculations** render the API's terms and the API's result side by side; the browser does no
   arithmetic on S/P/K_p. The two comparisons it does make (floor kept or breached, shortfall
   = floor − API minimum P) are integer minor units on API figures.
6. **`t=N h`** is hours from the response's `as_of`, labelled so; absolute UTC and local time are
   always shown beside it.
7. **Lending's venue line** comes from the same snapshot's `/overview` `completeness.missing`
   (C6 Lending carries no per-account list); a context mismatch between the two reads is an error,
   never a merge. Contract gap named for T16: LendingResponse has no pool account list.
   *Superseded (prp/2026-10-27-x86-lending-coherent):* the gap is closed. `capacity.unobserved`
   lists the uncounted pool accounts, each stale or unknown, read together with the authority. The overview is read only
   for the demo run, because two reads on either side of the six-hour boundary disagreed.
8. **Tooling**: vitest 4 + happy-dom + @vue/test-utils (Node 20 on the build box; vitest 5 and
   jsdom 30 need Node 22).
9. **Wiring**: three routes in `src/router/index.js` (upstream, listed in ATTRIBUTION.md); the
   upstream `/` home stays as it is.

## Run footer

ARCHITECT · tier=Sketch (the module design ran at Brief: `design/modules/ui/HANDOFF.md`) ·
signals = no named reviewer, reversible, nothing unbackfillable, uncontested, one module ·
thresholds v2. No reviewer pack on this body; no publish step (unattended, no tap). Consumers are
the table above; contracts are C6 only.
