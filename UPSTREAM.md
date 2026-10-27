# Upstream

| | |
|---|---|
| Project | MiroFish |
| URL | https://github.com/666ghj/MiroFish |
| Commit | `7657031ac01184afe2cb220f5ee3545573b5e843` (2026-10-01) |
| Tree | `dcc88f9b1da4145a06769a7f979d50d77e1dba25` |
| Fetched | 2026-10-27 |
| Licence | AGPL-3.0 (`LICENSE`, unchanged) |

## How it was imported

The tree at the pinned commit was exported as an archive (no upstream history, not a fork) and
committed with no file changed as the parentless commit
`949e9fb import: upstream engine at 7657031, unmodified`. Its tree hash equals the upstream
commit's tree hash above, which proves the import is byte-identical. That commit is merged into
the project history; everything after it is ours.

## How to diff

```bash
git tag upstream-7657031 949e9fb   # once per clone, if the tag is absent
git diff upstream-7657031 -- backend frontend   # upstream code we changed
git diff --name-status upstream-7657031         # every added, modified or deleted path
```

`checks/attribution.py` finds the import by the tag, or by the tree hash when the tag is absent,
and fails if a modified or deleted upstream path is missing from `ATTRIBUTION.md`.

## Upstream tests

- `backend/tests` (18 files, 129 tests at import) pass offline: they were run with networking
  disabled and are part of the merge gate's `testpaths`.
- `tests/test_local_star_count_fetch.py` fetches from the network and is excluded by the pytest
  configuration. `tests/test_local_star_history.py` runs offline (20 tests) and stays in.
