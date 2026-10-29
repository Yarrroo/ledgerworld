# Execution panels E1–E6 and the approval dialog (board item 133)

Source: `prp/2026-10-29-ux-pass/HANDOFF.md` — "Execution: every panel & action", "Approval &
execution state machine", "Responsive layout". The handoff's appendix wins on numbers.

## Who reads or writes this screen

| Consumer | What it relies on — kept unchanged |
| --- | --- |
| Operator (keyboard, phone) | One dialog; one primary action per stage; Escape closes only when no POST is in flight; focus trapped inside, returned to *Review plan*. |
| Judge path (`e2e/judge-path.spec.ts`, read-only) | `context` text `execution <id>`; every `[data-test^="leg-"]` is a leg (`leg-<kind>`) holding `leg-status`, `receipt-mode`, one `receipt`; `incident`, `no-legs`, `not-found`, `poll-error`, `no-execution` absent on a clean run. New hooks never start with `leg-`. |
| Narrated take, walkthrough | Route `/execution`; nothing posts from the screen. |
| `frontend/tests/unit/decide-execute.spec.js` | The guards: single-flight POSTs, unknown outcomes quarantined per run in tab memory, polling by approval id, answers bound to the screen they were asked on. All `data-test` hooks kept. |
| `e2e/ux/execution.spec.ts` (new) | Drives every dialog stage against a mocked `/api/v1` at 1440, 834, 390 px. |

Invariants that cannot be added later: a timed-out financial POST is never resent; the token never
reaches markup, URL or storage; approval and execution are two acts.

## The dialog: one stage at a time

`stage` is derived, never stored, from the flow the guards already keep:

```
review ──Confirm──▶ submitting ──201──▶ approved ──Execute──▶ executing ──read──▶ reconciled
   │                    │ no answer          │ expiry / 4xx / mode            │ unknown leg,
   │                    ▼                    ▼                                ▼ open incident
   │                 unknown (blocked)    expired (Execute disabled)        incident
```

* `executing` covers "Execution submitting / unknown": the known approval/execution id, *Reading
  status*, no Execute. The dialog now stays open after Execute (it used to close) and follows the
  polled read; Close returns focus to the opener and drops the used approval.
* `reconciled` / `incident` read the same polled execution the page shows; no resend, no reversal.
* Copy buttons on approval id and plan hash announce *copied* (or why not) in a polite live region.
* Phone (<768 px): the dialog is full height; its body scrolls and the action footer stays fixed.
  Every width: footer holds the stage's one primary action, then the way out.

## The page

E1 Execution context · E2 Approval review (opener + operator access) · E3 Approval summary (from
the execution read: approval id, snapshot, mode, read time) · E4 Leg tracker (Ready → Submitted →
Provider-confirmed → Reconciled per leg, raw status, amount; expands to E5 receipt) · E6 Incidents
(each with affected leg, provider/request ids, observed status, opened and last-read times).
Desktop: legs left, terms and incidents right. Tablet/phone: one column, terms above legs.

---
Run: architect tier Sketch (one view, spec fixed by the handoff); no reviewer pack on this node; not published.
