# Vet — the API base "/" fix

> Tier T2: the changed line decides where a bearer-token request goes (`frontend/src/api/v1.js`
> `request()`); 2 files, test delta present. Instruments: code review (medium, then low on the
> round-1 change), simplify (reuse, simplification, efficiency, altitude), security review.

## Round 1 (commit c37c701)

| Finding | Grade | Outcome |
|---|---|---|
| An empty path made `<base>/api/v1/` where the old join made `<base>/api/v1` | low | applied; proven by `names the API root itself without a trailing slash` (fails on c37c701) |
| The request test asserted only the first URL exactly | medium | applied: all three screens' URLs asserted exactly |
| `String()` around strings | low | applied |
| A protocol-relative loop repeated the table | low | applied: folded into the table as path variants |
| A request-level row repeated an `apiUrl` row | low | applied |
| An empty `VITE_API_BASE_URL` falls back to `http://localhost:5001` while `apiUrl(p, '')` is same-origin | low | recorded: an empty build value means "unset" for both clients (`index.js` uses the same `\|\|`); `apiUrl`'s `''` is a direct-call contract |
| A base already ending in `/api/v1` doubles the prefix | low | recorded: a misconfiguration the old join had too; no setting uses it |
| One shared base export for both clients | low | recorded: tidier, fixes nothing; axios joins correctly itself |

Security review: no findings. The paths are constants, the base is a trusted build value, and the
fix removes the route by which a token could reach host `api`.

## Round 2 (commit 0cb1d3d)

| Finding | Grade | Outcome |
|---|---|---|
| Without `String()`, a non-string `path` or base throws | low | recorded: all three callers pass literals, and the base is a Vite env string or a string literal |

Converged in 2 rounds: 0 high, 1 medium, 8 low; 5 applied (1 proven, 0 unproven), 4 recorded,
0 open. Coverage: read both files in full, the deletion in `request()`, `index.js` and the three
views' imports.
