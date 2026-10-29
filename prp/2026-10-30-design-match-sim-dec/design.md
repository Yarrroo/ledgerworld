# Design match 4 and 5: Simulation and Decisions as mockups 04 and 05

Contract: `prp/2026-10-29-ux-pass/MATCH.md` (shared items 1–8, "04 Simulation", "05 Decisions") and
`mockups/04-Simulation.png`, `mockups/05-Decisions.png`. Numbers come from the API, never the image.

## Consumers (who reads these screens and their hooks)

| Consumer | Reads | Kept / changed |
|---|---|---|
| A judge in a browser (goal g4) | the two pages at 1487, 834, 390 px | layout as the mockups, within the word budget |
| `scripts/judge-path.sh` → `e2e/judge-path.spec.ts` | `open-simulation`, `scrubber-slider`, `cursor`, `phase`, `#feed-title`, `compare`, `policies`, `policy-*`, `selected`, `cohort`, `view-execution` | hooks kept; the cursor reads "Round N of 18", the actor panel replaces "Actors up to round N" — the spec follows |
| `e2e/ux/match-shared.spec.ts` | hero action per screen | Decisions' hero has no button (the mockup's is in the plan column): `ACTION['/decisions']` becomes null |
| `e2e/ux/simulation*.spec.ts`, `decisions.spec.ts`, `copy-2.spec.ts`, `readable-labels.spec.ts`, `states.spec.ts` | the old panels | aligned to the new layout in the same commit |
| unit specs `simulation-*.spec.js`, `decide-execute.spec.js` | mounted views | aligned |
| `narrated-take.spec.ts`, `walkthrough.spec.ts` | page URLs only | unchanged |

## Simulation (/simulation)

hero (Compare policies) → selector row (Scenario · Branch · Cohort as read-only values with tooltips;
Scenario settings opens the families sheet) → left **Market relationships at round N** (the world map
with role icons; the edges the rounds up to the cursor add — requests, cited posts, journalled
moves — are the amber causal path, captioned with their hour) beside right **selected actor** (name,
"Selected actor · Round N", What changed timeline of the actor's own moves and the requests it
received, Ask this actor + Interview, operator access, Source evidence) → **round row** (play, Round
N of 18, Nh simulated, the 18-round horizon with the committed rounds selectable and the family's
shock round marked, Fork checkpoint, "Playback only · No funds move") → **Treasury cash path
(72-hour outlook)**: each policy branch's path (the base before it forks), the reserve floor, the
cursor's hour, and the red shortfall callout from No action's lowest point against the floor.
The action feed, the evidence graph and the round export move into one fold, "Source evidence".

## Decisions (/decisions)

hero (no button) → stepper Rehearse · **Compare** · Review → left **The gap we need to close** (big red
No-action shortfall below the floor, one plain line), **Cash waterfall (before plan)** (treasury
settled, each payment due before the low point, No action's lowest; floor line and gap), **Key
timing in this scenario** (Now / In Nh rows from the treasury and the family's delay) → right
**Three ways forward** radio rows (name, one line, Reserve outcome · Funding cost · Obligations unmet),
**Minimum projected cash** of the chosen plan against the floor, primary **Review current plan**,
links Compare scenario details and Open simulation, the no-approval footnote.

## Left out for want of an API field (said in the close-out)

The lender's capacity on its map node (the run API serves no capacity), and the mockup's scenario
name "Demo 01" (the run has an id, shown as "Demo run" with the id in the tooltip).
