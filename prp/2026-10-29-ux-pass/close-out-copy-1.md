# Copy pass 1 (Overview, Treasury, Lending) — Close-out
> Close-out (/dev-close). Source: COPY.md ← HANDOFF.md.
> Date: 2026-10-29

## What shipped
- `COPY.md` brought onto main verbatim from `design/ux-pass`.
- Each screen leads with one sentence built from the API's figures (`data-test="lead"`); a stale
  input adds one "Some figures were last seen <UTC>." line (`lead-stale`). A negative spendable
  or K_p never reads as money to use.
- Visible headings, tile labels and panel names use the glossary words; floor status reads
  "Above / Below your safety minimum" (`FLOOR_WORDS`).
- `components/HowWeKnow.vue`: a closed `<details>` per panel holding ids, K_p, S, P, authority
  and sources. Every earlier `data-test` hook is kept, moved inside it where it was mechanics.
- Visible honesty labels on Overview: "Simulated bank connection" / "Sandbox bank",
  "Scripted agents", "What-if". The shell bar and the "Open simulation" button are unchanged
  (the judge-path fixture names them).
- Sentence helpers in `api/v1.js`: `PLAIN`, `FLOOR_WORDS`, `dayText`, `amountWords`,
  `listWords`, `lastSeen`; `OWED` exported.

## Verification
- `bash scripts/ux-check.sh e2e/ux/copy-1.spec.ts`: 24 passed at 1440/834/390, judge path
  12 passed, `ux-check: green`.
- Older specs against one app: overview, treasury, lending, states, readable-labels,
  panel-jump, shell, overview-chart-labels: all passed (2 drawer tests skip by design).
- `checks/attribution.py`, `checks/no_secrets.py`: ok. No Python changed; the full pytest
  suite is the landing train's.

## Follow-ups / known gaps
- Simulation, Decisions and Execution leads (COPY.md templates) are not in this pass.
- The shell's mode label still reads "Simulated provider"; the judge-path fixture checks it.
- `dayText` prints a UTC day without the "UTC" label in lead sentences.
