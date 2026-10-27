# Coupled-world evidence review

23 October 2026 · cycle 10 · move J · design review only.

## Verdict

The coupled-world claim has fixture-backed wiring. Its demonstration still needs an actual recorded run. This pass strengthens exception rollback and keeps scripted evidence separate from live-model evidence. No product test, provider operation or model experiment ran.

## What we understood

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 310" width="340" style="max-width:100%;height:auto;color:inherit" role="img" aria-label="A valid payout receipt cannot substitute for the missing social-response evidence">
<g fill="none" stroke="currentColor" stroke-width="1.5"><rect x="10" y="10" width="320" height="54" rx="5"/><rect x="10" y="102" width="320" height="54" rx="5"/><rect x="10" y="194" width="320" height="54" rx="5"/><path d="M170 64V102M170 156V194"/><path d="M164 94L170 102L176 94M164 186L170 194L176 186"/><path d="M330 221H338V37H330" stroke-dasharray="4 4"/><path d="M323 29L337 45M337 29L323 45" stroke-width="3"/></g>
<g fill="currentColor" font-family="system-ui,sans-serif" font-size="13" text-anchor="middle"><text x="170" y="33">Post → scoped observation → request</text><text x="170" y="51">Scripted fixture; live choice unmeasured</text><text x="170" y="88">trace ids connect</text><text x="170" y="125">Intent → cleared journal → capacity</text><text x="170" y="143">Rollback and checkpoint guards required</text><text x="170" y="180">separate observed approval</text><text x="170" y="217">Sandbox payout receipt</text><text x="170" y="235">Provider GET and journal reconciliation</text><text x="170" y="281">Receipt-to-agent-proof shortcut refused</text></g>
</svg>
<figcaption><strong>A valid payout receipt cannot fill a missing social-response trace.</strong> The recording must carry both evidence paths.</figcaption>
</figure>

## Published requirements and provisional judging lenses

Sources: event facts in the bundle's `rules.md`, sections Submission and Judging; system brief §7, §13 and §17. The event FAQ verifies a working demo, a video under five minutes and a repository with setup instructions. Criteria names remain search-only, with no verified weights. No official or weighted score is assigned here; the existing blocker remains open.

| Requirement or provisional lens | Plan assessment | Evidence still required after build |
|---|---|---|
| Working demo, video and setup | Planned through T23, T26–T28 | Successful deployed read path, actual recording and setup check |
| Finance/product value, provisional | Covered by realised feasibility and visible lender constraint | Recorded result linked to its ledger, with hypothetical/observed labels |
| Airwallex relevance, provisional | Covered by bounded approval and reconciled advance/payout | Fresh sandbox receipt, GET confirmation and mode labels; fake is not sandbox |
| Agentic behaviour and controls, provisional | Partial evidence: scripted response chain and scope guards | Declare model provenance; a script cannot prove independent model choice |
| Technical execution, provisional | Fixture-backed plan with restoration gap tightened below | Product accepts must run; page rendering is not a runtime test |

## Walk the recording backwards

| Final claim | Required predecessor | Refuse the claim when |
|---|---|---|
| Report explains the run | Structured values and resolvable evidence ids from that run/branch | A number or quoted observation has no source |
| Payout reconciled | C3 approval, provider GET, journal and receipt as_of | Receipt is merely SENT, fake, unrelated or contradicted by an open incident |
| Chosen policy protected obligations | Paired branches and realised ledger feasibility | Projected actions are substituted for realised outcomes |
| Other actors constrained the lender | Journal ← lender intent ← request ← borrower intent ← visible post | A final balance is shown without the connecting trace |
| A genuinely fresh branch ran | Branch created during the run from the named checkpoint | Cached replay is relabelled fresh |

## What we measured and changed

This was a file-level review, not a benchmark. `round-rollback.json` checked the ledger and transcript but did not require all volatile state to return to its round-start capture. `branch-isolation.json` named a memory namespace without pinning immutable records and the event/delivery cursors. The fixtures, HANDOFF, T08/T09 briefs and system brief now require a complete capture and a scripted retry against a clean control. The assertion covers pre-completion exceptions; it does not promise power-loss atomicity across stores.

The scripted coupled-chain plan is conditional on observed posts and requests. That proves the declared wiring and supports a controlled comparison. T28 and system brief §13 now require the opening shot list to declare run/branch/checkpoint/seed and model provenance separately from provider mode, freshness and replay status. No live-model result is inferred from a sandbox receipt or an observation hash.

## What cannot be added later

Keep the original observation/evidence references, branch/checkpoint identity, model provenance and committed state capture. A later caption cannot reconstruct an observation that was never retained. Actor-private source material remains scope-filtered; a public explanation does not grant access to every actor's raw memory.

## Shapes considered

Keep both the offline scripted guard and explicitly labelled runtime evidence. Replacing the scripted test with a live-model gate is rejected: it loses deterministic regression coverage and introduces network dependence. Treating a payout receipt as proof of the whole world is rejected by the figure. No new task, goal, ranking, spend or infrastructure is proposed.

## Assumptions marked for correction

- The original coupled-world-first recording order remains binding. The brief author may correct presentation through canonical mockups; none has arrived.
- Existing T08, T09 and T28 own these refinements. If a full process-crash recovery guarantee is requested, it requires a separate durability design rather than calling these exception tests sufficient.

## Amendment · early failure and concurrent abort · 24 October

The requirement that a round commits whole or not at all also applies before intent validation. The previous system brief and HANDOFF said “Any failure in 6–10”; they did not explicitly cover a failed actor step or require sibling writers to stop before restoration. This is a document-level gap, not an observed product defect.

| Surface | Superseded boundary | Required boundary |
|---|---|---|
| Failure coverage | Exceptions in steps 6–10 | Capture before step 1; abort on unhandled exception or cancellation before durable completion in steps 1–10 |
| Restoration | Complete capture, writer lifecycle unspecified | Close admission, cancel/join round-owned work and children, establish quiescence, then restore; refuse reuse if quiescence is unproved |
| Regression evidence | Settlement and pre-append faults | Add event-delivery fault, actor failure and coordinator cancellation; barrier-controlled sibling cleanup attempts a final provisional write that restoration must remove |

T08 owns the refinement; its whole-file accept and board rank stay unchanged. Invalid intent and repaired malformed output remain ordinary committed results. The fixture describes future assertions only. No concurrency test, upstream API experiment or independent reviewer ran in this pass; fresh live-model responses and external charges are outside scripted rollback equivalence. Official criteria remain unresolved and no weighted score is assigned.

## Verification boundary

Fixture JSON and document links are checked in this cycle. Product accepts in HANDOFF remain future build commands. The criteria-source blocker, registration/acceptance status and other external blockers are not closed by this review. No original brief or clone was edited. No independent reviewer ran for this bounded pre-mortem.
