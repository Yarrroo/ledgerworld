"""Recording pre-flight: say GO, or name the first thing that would spoil the take.

Usage: python checks/recording_ready.py BASE_URL

Anonymous GETs only, against the deployed demo (`BASE_URL` is the site; `/api/v1` is added unless
it is already there). It reads the API state behind the screens the take films, in the order of
the stop conditions in docs/video-script.md "Recording prerequisites":

  reachable             GET /overview answers 200
  prepared_run          the overview names a prepared demo run_id
  prepared_execution    ... and the execution associated with it
  decisions             GET /decisions/{run_id} answers 200 and is no longer pending
  feasible_policy       a policy is selected and feasible (all_infeasible stops the take)
  execution_read        GET /executions/{execution_id} answers 200
  execution_reconciled  every leg settled, carries a provider receipt and is reconciled; no open
                        incident (a failed leg is reconciled too, and still spoils the take)

One line per check (`ok`, `FAIL` or `skip` when an earlier failure leaves nothing to read), then
`GO` or `NO-GO: <first failure>`. A malformed answer, or a later read that gets no answer, fails
the check in hand. Exit 0 on GO, 1 on NO-GO, 2 when the first read gets no answer or on bad
usage. It never writes and never sends a credential. Stdlib only.
"""

from __future__ import annotations

import http.client
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

TIMEOUT_S = 15
USER_AGENT = "ledgerworld-recording-ready/1"
CHECKS = ("reachable", "prepared_run", "prepared_execution", "decisions", "feasible_policy",
          "execution_read", "execution_reconciled")

# fetch(url) -> (HTTP status, parsed JSON body or None); raises Unreachable when no answer came.
Fetch = Callable[[str], tuple[int, object]]


class Unreachable(Exception):
    pass


class NoGo(Exception):
    pass


def http_get(url: str) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        raise Unreachable(str(getattr(exc, "reason", exc))) from exc
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def api_base(base: str) -> str:
    base = base.rstrip("/")
    return base if base.endswith("/api/v1") else base + "/api/v1"


def _read(fetch: Fetch, api: str, path: str, what: str) -> dict:
    try:
        status, body = fetch(f"{api}/{path}")
    except Unreachable as exc:
        if path == "overview":
            raise
        raise NoGo(f"{what} got no answer: {exc}") from exc
    if status != 200:
        code = body.get("code") if isinstance(body, dict) else None
        raise NoGo(f"{what} answered HTTP {status}" + (f" ({code})" if code else ""))
    if not isinstance(body, dict):
        raise NoGo(f"{what} answered 200 without a JSON object")
    return body


def _reconciled(execution: dict) -> str:
    """'' when the receipt is reconciled, else what is not."""
    legs = execution.get("legs") or []
    if not legs:
        return "the execution has no legs"
    for leg in legs:
        name = leg.get("leg_id") or leg.get("kind") or "?"
        if not leg.get("receipt"):
            return f"leg {name} has no provider receipt (state {leg.get('state')})"
        if leg.get("reconciled") is not True:
            return f"leg {name} is not reconciled (state {leg.get('state')})"
        if leg.get("state") != "settled":
            return f"leg {name} is {leg.get('state')}, not settled"
    open_ = [i.get("incident_id") for i in execution.get("incidents") or []
             if i.get("state") == "open"]
    return f"open incident {', '.join(map(str, open_))}" if open_ else ""


def run(base: str, fetch: Fetch = http_get) -> tuple[list[tuple[str, str, str]], int]:
    """Each check as (verdict, name, detail) and the exit code. Raises Unreachable."""
    api = api_base(base)
    lines: list[tuple[str, str, str]] = []
    pending = list(CHECKS)

    def ok(detail: str) -> None:
        lines.append(("ok", pending.pop(0), detail))

    try:
        overview = _read(fetch, api, "overview", "overview")
        ok(f"{api} mode {overview.get('mode', '?')}, snapshot {overview.get('snapshot_id', '?')}")
        demo = overview.get("demo") or {}
        run_id, execution_id = demo.get("run_id"), demo.get("execution_id")
        if not run_id:
            raise NoGo("no prepared run: overview.demo.run_id is null")
        ok(f"run {run_id}")
        if not execution_id:
            raise NoGo(f"run {run_id} has no associated execution: overview.demo.execution_id is null")
        ok(f"execution {execution_id}")
        quoted = urllib.parse.quote(run_id, safe="")
        decisions = _read(fetch, api, f"decisions/{quoted}", f"decisions of {run_id}")
        if decisions.get("status") == "pending":
            raise NoGo(f"decisions of {run_id} are still pending")
        ok(f"status {decisions.get('status')}, {len(decisions.get('results') or [])} results")
        feasible = sorted({r.get("policy") for r in decisions.get("results") or []
                           if r.get("feasible") is True})
        selected = decisions.get("selected")
        if decisions.get("status") == "all_infeasible" or not feasible:
            raise NoGo(f"every policy of {run_id} is infeasible")
        if decisions.get("status") != "selected" or selected not in feasible:
            raise NoGo(f"decisions of {run_id} are {decisions.get('status')} with selected "
                       f"{selected}, not a feasible selection")
        ok(f"feasible {', '.join(map(str, feasible))}; selected {selected}")
        execution = _read(fetch, api, f"executions/{urllib.parse.quote(execution_id, safe='')}",
                          f"execution {execution_id}")
        ok(f"{len(execution.get('legs') or [])} legs")
        problem = _reconciled(execution)
        if problem:
            raise NoGo(f"execution {execution_id} not reconciled: {problem}")
        ok("every leg settled, receipted and reconciled; no open incident")
    except (NoGo, AttributeError, TypeError) as failure:  # the last two: a field of the wrong shape
        detail = str(failure) if isinstance(failure, NoGo) else f"malformed answer: {failure}"
        lines.append(("FAIL", pending.pop(0), detail))
        lines.extend(("skip", name, "") for name in pending)
        return lines, 1
    return lines, 0


def main(argv: list[str], fetch: Fetch = http_get) -> int:
    if len(argv) != 1 or urllib.parse.urlsplit(argv[0]).scheme not in {"http", "https"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        lines, code = run(argv[0], fetch)
    except Unreachable as exc:
        print(f"UNREACHABLE {api_base(argv[0])}: {exc}")
        return 2
    for verdict, name, detail in lines:
        print(f"{verdict:<4} {name:<20} {detail}".rstrip())
    failed = next((f"{name}: {detail}" for verdict, name, detail in lines if verdict == "FAIL"), "")
    print(f"NO-GO: {failed}" if code else "GO")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
