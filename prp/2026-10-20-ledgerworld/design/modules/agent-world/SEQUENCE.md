# LedgerWorld first build window

Cycle 11 · move S · prepared 23 October 2026; sequence rechecked in cycle 14 on 24 October. This is a conditional sequence, not permission to build, publish or spend. Refresh it at the plan freeze.

## Verdict

Protect the offline money path first. In the first build window, target the upstream base, contracts, deterministic test doubles and LF-1 ledger validation. The coupled round cannot start until both the ledger and doubles are available. No runtime or task-duration estimate has been measured.

## Start gate

The nominal window is **25 Oct 04:30 UTC to 27 Oct 04:30 UTC**. Its midpoint is 26 Oct 04:30 UTC. These are planning checkpoints, not promised task completion times. Build starts only after T0, the event acceptance notice, the owner's explicit flip and completion of P3 (entry repository). Commit, merge, push and deploy remain separate owner checkpoints unless an applicable standing grant is verified from its authoritative configuration; this plan grants none.

Application and owner participation are reported complete: the owner reported submission on track 07 and later accepted the team invitation on 22 Oct, as relayed in the operational records. That is reported confirmation, not a portal inspection by this session. It does not establish acceptance, sandbox keys or connected-account enablement. P1 also asks for platform access; its whole board task is not marked done by this document.

If acceptance or the flip arrives late, do not silently move the event's deadlines or claim a full window remains. Record the actual authorised start and unfinished prerequisites; the owner decides any scope or milestone change. Before then, continue design only.

## Dependency model

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 350 450" width="350" style="max-width:100%;height:auto;color:inherit" role="img" aria-label="Missing provider keys do not block the offline ledger and test-double join">
<g fill="none" stroke="currentColor" stroke-width="1.5"><rect x="10" y="10" width="330" height="46" rx="5"/><path d="M175 56V80M175 80H90V104M175 80H260V104"/><rect x="10" y="104" width="160" height="56" rx="5"/><rect x="190" y="104" width="150" height="56" rx="5"/><path d="M90 160V184"/><rect x="10" y="184" width="160" height="56" rx="5"/><path d="M90 240V264"/><rect x="10" y="264" width="160" height="56" rx="5"/><path d="M90 320V346H175V370M260 160V346H175"/><rect x="10" y="370" width="330" height="56" rx="5"/></g>
<g fill="currentColor" text-anchor="middle" font-family="system-ui,sans-serif" font-size="13"><text x="175" y="30">Authorised start → T01</text><text x="175" y="47">Upstream base and offline merge gate</text><text x="175" y="96">unlocks</text><text x="90" y="127">T02 · contracts</text><text x="90" y="146">C1–C6 examples</text><text x="260" y="127">T06 · doubles</text><text x="260" y="146">No model / graph key</text><text x="90" y="177">unlocks</text><text x="90" y="207">T03 · fixtures</text><text x="90" y="226">Hand-checked LF-1/LF-2</text><text x="90" y="257">unlocks</text><text x="90" y="287">T04 · ledger</text><text x="90" y="306">LF-1 and invariants</text><text x="175" y="363">join both prerequisites</text><text x="175" y="394">T07 · scoped finance tools</text><text x="175" y="413">Then T08 · coupled round</text></g>
</svg>
<figcaption><strong>Missing provider keys do not block the offline ledger and test-double join.</strong> Keep the credential-dependent lane separate instead of parking both lanes.</figcaption>
</figure>

This diagram shows prerequisites, not a new board ranking or a request for extra builder capacity. T02 and T06 are independently eligible after T01. Use existing authorised capacity only. If only one builder is available, retain the board's existing selection order; parallel eligibility is not a concurrency grant.

## Planning checkpoints

| Checkpoint | Target evidence | If incomplete |
|---|---|---|
| Authorised start | Acceptance and flip/P3 evidence; T01 can run under the approved repository procedure | Name the unmet gate; no clone/code/provider action in warm-up |
| First day, by 26 Oct 04:30 UTC | Target T01 foundation, T02 validated contracts, T06 deterministic doubles and T03 fixture truth. Retain each task's own accept and offline merge gate output | Record which task and prerequisite are missing; no percentage or green status inferred from file existence |
| Second day, by 27 Oct 04:30 UTC | Target T04 LF-1 ledger/invariant accepts plus merge gate; retain integer-money, reservation and P-versus-S checks | Report the failing command and unmet invariant; do not weaken the accept or replace results with fixture constants |
| After those proofs | T05 lending becomes eligible after T04. T07 finance tools becomes eligible after T04 and T06; T08 waits for T07 | Do not start a consumer against a stub that silently changes a contract |

T12 fake connector and T22 KPI runner are eligible after T02; they need no sandbox or model credentials. Their eligibility does not let them displace the existing ranking or consume new capacity. Full UI, deployed demo, live sandbox run and reverse stress are not first-window completion claims.

## Proof commands after build authorisation

These are copied from the current board; none was executed by this warm-up session.

| Task and purpose | Task accept |
|---|---|
| T01 foundation | `bash checks/merge.sh` |
| T02 contracts | `uv run pytest -q tests/contracts/test_contracts.py` |
| T03 fixture truth | `uv run pytest -q tests/fixtures/test_fixture_data.py` |
| T06 offline doubles | `uv run pytest -q tests/testing/test_doubles.py` |
| T04 ledger | `uv run pytest -q tests/finance/test_ledger.py tests/finance/test_fixtures.py` |

Run the existing merge gate after each completed task. A task accept does not bypass its dependency or the publication checkpoint. Check the existing T01 network-test exclusions; a green offline gate must not depend on real provider, model or hosted graph-memory calls. PostgreSQL evidence remains separately labelled; SQLite success is not a PostgreSQL result.

## Dependency-critical route beyond the first window

The board's longest dependency-count route to T28 (submission pack) is:

T01 foundation → T02 contracts → T03 fixtures → T04 ledger → T07 tools → T08 rounds → T09 branches → T11 policies → T13 execution → T16 API → T17 money screens → T18 simulation screen → T26 browser proof → T28 submission pack.

This is a graph path, **not a duration-based critical-path calculation**. All incoming dependencies still apply, including T06→T07, T05+T08→T10→T11, T12→T13, T19+T25→T26 and T27→T28. P2 gates T15; P4 gates T25; both therefore affect the later sandbox demonstration. No task has been removed, re-ranked or rescheduled on the board. A duration-based ETA needs actual build throughput, which does not exist yet.

## Failure responses and authority

| Condition | Safe continuation | Must not do |
|---|---|---|
| Sandbox keys absent | Offline tests and fake transport; preserve fake labels | Turn on sandbox because a credential appears, or call production |
| Model or graph key absent | ScriptedModel and FakeGraphMemory for tests | Present a scripted branch as independent live-model evidence |
| External fixtures absent | Existing LF-1/LF-2 default; preserve the open decision | Invent supplied fixtures or silently change financial expectations |
| Canonical mockup arrives | Next design cycle incorporates it; scope/ranking conflict goes to T2 | Treat provisional layout as approved or override the author's ranking |
| Contract or money test fails | Record task, command, output and owner of the seam | Average away a shortfall or relax an obligation/floor |
| Schedule slips | Report completed proof and remaining prerequisites at each checkpoint | Claim this planning sequence authorised a scope cut, spend or deployment |

## Pre-start recheck · 24 October

The current board still has the same task order, prerequisite parks and first-window accepts. The start window and targets above are unchanged. The dated operational preflight reports acceptance unconfirmed and sandbox/graph credentials absent from the inspected inventories; this is a relayed inventory check, not a provider login by this session. Repository publication and deployment authorisation are also unconfirmed. None of these reports authorises a start. Offline work remains conditional on T0, acceptance, the owner's explicit go and P3; credential-dependent work remains separately gated. Keep the existing owner decision in one place rather than requesting a duplicate start decision.

The next verification is at freeze, or on a new acceptance/owner decision, canonical mockup, external fixture set or changed board prerequisite. Do not repeat a failed rubric lookup or a credential probe without new input. The later T08 failure/cancellation refinements remain owned by the round coordinator and do not add a first-window dependency or change its ranking.

## Source and drift checks

Sources read in cycle 11: the 40-task board and its dependency parks; bundle briefs T01/T02/T04/T06; system brief §7/§13; agent-world and ledger handoffs; existing operational confirmation of application and invitation. The shortened question identifiers in the operational log did not resolve through the question CLI, so no canonical answer payload is claimed as read. The two dated relay messages and both PM logs agree on the reported status.

`day1.md` is the warm-up entry point. An identical `modules/agent-world/SEQUENCE.md` carries this plan through the design mirror to the builder. Verify equality when refreshing either copy, particularly at freeze. No external contact, portal login, new schedule, implementation, repository publication or deployment was performed for this plan.
