# Design match 4: Simulation as mockup 04

Contract: `prp/2026-10-29-ux-pass/MATCH.md` (shared items 1–8, "04 Simulation") and
`mockups/04-Simulation.png`. Numbers come from the API, never the image.

## Consumers (who reads this screen and its hooks)

| Consumer | Reads | Kept / changed |
|---|---|---|
| A judge in a browser (goal g4) | `/simulation` at 1487, 834, 390 px | layout as mockup 04, within the word budget (241 words) |
| `scripts/judge-path.sh` → `e2e/judge-path.spec.ts` | `open-simulation`, `scrubber-slider`, `cursor`, `phase`, `#feed-title`, `inspector`, `compare` | hooks kept; the cursor reads "Round N of 18 · Nh simulated" on the demo world |
| `e2e/ux/match-shared.spec.ts` | hero action `Compare policies`, honesty labels, tooltips, word budget | kept |
| `e2e/ux/match-simulation.spec.ts` | layout order, hero, selector row, map, selected actor, scrubber row, cash path + shortfall, tooltips, word budget at 1487, 834, 390 px | new spec for item 161 |
| `e2e/ux/simulation*.spec.ts`, `copy-2.spec.ts`, `readable-labels.spec.ts`, `states.spec.ts` | the Simulation panels | aligned to mockup 04's layout and copy in the same commit |
| unit specs `simulation-*.spec.js`, `ux-panels.spec.js` | mounted `Simulation.vue` | aligned and extended with mockup 04 checks |
| `narrated-take.spec.ts`, `walkthrough.spec.ts` | page URLs only | unchanged |

## Simulation (/simulation)

hero (Compare policies) → selector row (Scenario · Branch · Cohort as read-only values with tooltips;
Scenario settings opens the families sheet) → left **Market relationships at round N** (the world map
with role icons; the edges the rounds up to the cursor add — requests, cited posts, journalled
moves — are the amber causal path, captioned with their hour) beside right **selected actor** (name,
"Selected actor · Round N", What changed timeline of the actor's own moves and the requests it
received, Ask this actor + Interview, operator access, Source evidence) → **round row** (play, Round
N of 18 · Nh simulated, the 18-round horizon with the committed rounds selectable and the family's
shock round marked, Fork checkpoint, "Playback only · No funds move") → **Treasury cash path
(72-hour outlook)**: each policy branch's path (the base before it forks), the reserve floor, the
cursor's hour, and the red shortfall callout from No action's lowest point against the floor.
The action feed, the evidence graph and the round export move into one fold, "Source evidence".

## Left out for want of an API field (said in the close-out)

The lender's capacity on its map node (the run API serves no capacity), and the mockup's scenario
name "Demo 01" (the run has an id, shown as "Demo run" with the id in the tooltip).

## Route record

Brief · thresholds v2 · one reversible UI module; no storage, API or execution contract change.
The supplied mockup is the binding shape. Existing Scrubber and WorldMap are extended; CashPaths
is rebuilt around the same run response. No new dependency or external consumer is introduced.
No reviewer pack. Expanded system-design artifacts, external inventory, publishing and multi-agent
panels are skipped: this order requests a one-screen local design and a solo implementation.
