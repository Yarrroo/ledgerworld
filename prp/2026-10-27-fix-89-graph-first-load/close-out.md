# Live simulation graph draws on first load — Close-out
> Close-out (/dev-close). Source: review finding F1, `prp/2026-10-27-xreview-t18-screen-live-simulation-with-one-scru/report.md`.
> Date: 2026-10-27

## What broke, and why

The reused graph view (`GraphPanel.vue`, upstream, unmodified) draws only from a non-immediate
watch on `graphData` and from window resize. The Live simulation screen renders its content inside
`ScreenShell` only once a run body exists, so `GraphPanel` mounted with its data already set and
never drew it. An unchanged refresh returns the same graph object (`same()` in `Simulation.vue`), and
a completed run is not polled, so the graph stayed blank until a scrub or a resize.

## What shipped

- `frontend/src/components/LiveGraph.vue` (new): mounts `GraphPanel` with no data and hands the
  graph over once mounted, so the first graph is a change it draws. Other attributes and events
  fall through unchanged.
- `frontend/src/views/Simulation.vue`: uses `LiveGraph` in place of `GraphPanel` (import plus tag).
- `frontend/tests/unit/simulation-view.spec.js`: `open()` can mount the real graph view (with i18n);
  new test "the real graph view" asserts drawn nodes on first load with no scrub or resize, and the
  same count after an unchanged refresh.

## Verification

- Regression test: fails before the fix (`expected 0 to be greater than 0`), passes after.
- `npx vitest run` (frontend, all 4 spec files): 102 passed. `npm run build`: built.
- `checks/attribution.py` ok (no upstream file changed), `checks/no_secrets.py` ok.
- Browser: Playwright sweep at 390, 768 and 1440 px, 4 of 4 nodes drawn on first load and after
  refresh, no horizontal scroll (`ux-sweep.md`, `ux/`).
- The full `checks/merge.sh` was not run here; the landing train runs it.

## Docs updated

- None needed: `prp/2026-10-27-t18-simulation/design.md` says the upstream `GraphPanel` is reused,
  which still holds through the adapter.

## Follow-ups / known gaps

- The same review's F2–F5 (fork follow-through, selection kept after scrubbing back, request
  evidence IDs, mixed-replay export) are separate corrections. The adapter does not remount
  `GraphPanel`, so a later F3 fix can clear its selection without blanking the graph again.
- Phone: the upstream graph overlay (edge-label toggle, title) can cover a node near the top edge;
  pre-existing, unchanged here (`ux/graph-phone.png`).
- Upstream callers of `GraphPanel` (Main, Simulation run, Report, Interaction views) start with
  `graphData = null` and load after mount, so they do not hit this path.
