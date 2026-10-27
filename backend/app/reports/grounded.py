"""Grounded reports: every number in the prose comes from a signed structured result.

g2 `report_numbers_grounded` (system brief §13: no fabricated comparison, receipt or probability).
A structured result is a set of named figures (Money or an integer count) under one evidence id,
signed with HMAC-SHA256 by whoever produced it; the key is the caller's, never the model's.

The model writes each figure as a placeholder ``{{<evidence_id>#<figure>}}`` and the placeholder
is filled with the figure's rendered value, currency included. A number the model writes itself
rejects the draft, even one a figure carries: its unit would be the model's (``EUR 10,000.00``
against a USD figure, a count read as ``3%``). So do a placeholder naming no figure, a unit
written beside a fill (a currency before it, a percent, rate or scale after it), and a fill that
runs into a neighbouring digit, sign or point (``3`` beside ``3`` reads 33). The unit check is a
list of the usual forms, not a parser; a unit it does not list passes. A rejected draft gets one
redraft with the reasons; a rejected redraft gives way to a template written from the results
alone. Every number in the returned text is one fill, linked to its evidence id, on all three
paths.

A number is any run of decimal digits, so an identifier like ``LF-1`` or ``round 4`` counts.
Figure and kind names hold no digit for the same reason: the template prints them. Numbers spelt
as words and numerals outside the decimal digits (superscripts, Roman numerals) are not detected.

``GroundedReportAgent`` extends the upstream ``ReportAgent`` with ``write_section``; it reads
signed results, never graph memory, and refuses a result whose signature does not verify.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.finance.schemas import Count, Money, Sha256, to_decimal
from app.services.report_agent import ReportAgent

EvidenceId = Annotated[str, StringConstraints(pattern=r"^[^\s{}#]{1,128}$")]
# Printed by the template, so a digit here would be a number no result carries.
Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,63}$")]
Figure = Money | Count

PLACEHOLDER = re.compile(r"\{\{\s*([^\s{}#]+)#([^\s{}#]+)\s*\}\}")
# A unit written beside a fill is the model's, not the figure's: a currency before it, a rate or a
# scale after it (a count as "USD 3", "3 percent", money as "USD 10,000.00 million").
UNIT_BEFORE = re.compile(r"([$€£¥]|\b[A-Z]{3})\s*$")
UNIT_AFTER = re.compile(
    r"\s*([%‰]|(?:percent|per\s*cent|bps|basis\s+points?|thousand|million|billion|trillion"
    r"|mn|bn|k|m|x)\b)",
    re.IGNORECASE,
)
# Grouped thousands or plain digits with an optional fraction; a minus only where it is not a
# hyphen inside a word (in "LF-1" the number is 1).
NUMBER = re.compile(r"(?:(?<!\w)-)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")

SYSTEM_PROMPT = (
    "You write one section of a treasury simulation report from signed structured results. "
    "Write every number as a placeholder {{<evidence_id>#<figure>}} naming a figure listed "
    "below; it is replaced with the figure's value. Write no other digits: no dates, rounds, "
    "identifiers, percentages or estimates. Never invent a comparison, receipt or probability."
)


def placeholder(evidence_id: str, figure: str) -> str:
    return "{{" + evidence_id + "#" + figure + "}}"


class UnverifiedResult(ValueError):
    """A structured result whose signature does not match its content under the key."""


class SignedResult(BaseModel):
    """Named figures under one evidence id, with the HMAC-SHA256 of their canonical form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: EvidenceId
    kind: Label
    figures: Annotated[dict[Label, Figure], Field(min_length=1)]
    signature: Sha256


def _mac(key: bytes, result: SignedResult) -> str:
    if not isinstance(key, bytes) or not key:
        raise ValueError("a signing key is non-empty bytes")
    body = result.model_dump(exclude={"signature"})
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def sign_result(
    evidence_id: str, kind: str, figures: dict[str, Any], *, key: bytes
) -> SignedResult:
    """Validate the figures (Money or a count, never a float) and sign them."""
    unsigned = SignedResult(
        evidence_id=evidence_id, kind=kind, figures=figures, signature="0" * 64
    )
    return unsigned.model_copy(update={"signature": _mac(key, unsigned)})


def verify_result(result: SignedResult, *, key: bytes) -> SignedResult:
    """The result itself, or ``UnverifiedResult`` when its content is not what was signed."""
    if not hmac.compare_digest(_mac(key, result), result.signature):
        raise UnverifiedResult(f"result {result.evidence_id!r}: signature does not verify")
    return result


def render(value: Figure) -> str:
    """A figure as the report prints it: ``USD 42,000.00`` for Money, ``1,234`` for a count."""
    if isinstance(value, Money):
        whole, _, frac = to_decimal(value).partition(".")
        sign = "-" if whole.startswith("-") else ""
        grouped = f"{sign}{int(whole.lstrip('-')):,}"
        return f"{value.currency} {grouped}" + (f".{frac}" if frac else "")
    return f"{value:,}"


def _amount(value: Figure) -> Decimal:
    return Decimal(to_decimal(value)) if isinstance(value, Money) else Decimal(value)


@dataclass(frozen=True)
class FigureRef:
    evidence_id: str
    figure: str


@dataclass(frozen=True)
class NumberLink:
    """A span of the report text and the figure it was filled from."""

    start: int
    end: int
    text: str
    ref: FigureRef


def _within(m: re.Match, spans) -> bool:
    return any(s.start <= m.start() and m.end() <= s.end for s in spans)


@dataclass(frozen=True)
class GroundedReport:
    title: str
    text: str
    links: tuple[NumberLink, ...]
    path: Literal["draft", "redraft", "template"]
    rejected: tuple[str, ...]  # why each failed attempt was refused, oldest first

    def unlinked(self) -> list[str]:
        """Numbers in the text that no link covers; empty for every report this module returns."""
        return [m.group() for m in NUMBER.finditer(self.text) if not _within(m, self.links)]


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


def _table(results: Sequence[SignedResult]) -> dict[FigureRef, Figure]:
    ids = [r.evidence_id for r in results]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(f"two results share an evidence id: {repeated}")
    return {FigureRef(r.evidence_id, k): v for r in results for k, v in r.figures.items()}


def ground(
    draft: str, results: Sequence[SignedResult]
) -> tuple[str, tuple[NumberLink, ...], list[str]]:
    """Fill the draft's placeholders and link its numbers: (text, links, problems).

    The text is usable only when ``problems`` is empty: then every number in it is one fill.
    """
    table = _table(results)
    out: list[str] = []
    links: list[NumberLink] = []
    unknown: list[_Span] = []  # placeholders naming no figure, already a problem
    problems: list[str] = []
    length = 0
    if not draft.strip():
        problems.append("the draft is empty")

    def emit(text: str) -> _Span:
        nonlocal length
        out.append(text)
        length += len(text)
        return _Span(length - len(text), length)

    pos = 0
    for m in PLACEHOLDER.finditer(draft):
        emit(draft[pos:m.start()])
        ref = FigureRef(m.group(1), m.group(2))
        if ref in table:
            span = emit(render(table[ref]))
            links.append(NumberLink(span.start, span.end, out[-1], ref))
            unit = UNIT_BEFORE.search(draft, 0, m.start()) or UNIT_AFTER.match(draft, m.end())
            if unit:
                problems.append(
                    f"the figure {m.group()} carries a unit the draft added: {unit.group(1)!r}")
        else:
            problems.append(f"the placeholder {m.group()} names no figure of a signed result")
            unknown.append(emit(m.group()))
        pos = m.end()
    emit(draft[pos:])
    text = "".join(out)

    rest = PLACEHOLDER.sub("", draft)
    brace = min((i for i in (rest.find("{"), rest.find("}")) if i >= 0), default=-1)
    if brace >= 0:
        problems.append(f"a malformed placeholder near {rest[max(0, brace - 40):brace + 1]!r}")
    amounts = {_amount(v) for v in table.values()}
    for m in NUMBER.finditer(text):
        if _within(m, links) or _within(m, unknown):
            continue
        if any(ln.start < m.end() and m.start() < ln.end for ln in links):
            # A fill beside a digit reads as one number neither side carries ("3" + "3" is 33).
            problems.append(f"the number {m.group()} in the filled text is not one figure")
        elif Decimal(m.group().replace(",", "")) in amounts:
            problems.append(f"the number {m.group()} is written out, not a placeholder")
        else:
            problems.append(f"the number {m.group()} is in no signed result")
    return text, tuple(links), problems


def template_draft(results: Sequence[SignedResult]) -> str:
    """The fallback section: one sentence per result, every figure a placeholder."""
    lines = []
    for r in results:
        parts = "; ".join(
            f"{k.replace('_', ' ')} {placeholder(r.evidence_id, k)}" for k in r.figures
        )
        lines.append(f"{r.kind.replace('_', ' ').capitalize()}: {parts}.")
    return "\n".join(lines)


class _NoGraphMemory:
    """Stands in for the upstream graph tools: a grounded section never reads graph memory."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):  # copy, pickle and hasattr probe these; they do not exist
            raise AttributeError(name)
        raise RuntimeError(f"a grounded report reads signed results, never graph memory ({name})")


class GroundedReportAgent(ReportAgent):
    """The upstream ReportAgent with sections whose every number traces to a signed result."""

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        *,
        key: bytes,
        llm_client=None,
    ) -> None:
        super().__init__(
            graph_id,
            simulation_id,
            simulation_requirement,
            llm_client=llm_client,
            zep_tools=_NoGraphMemory(),
        )
        self._key = key

    def write_section(self, title: str, results: Sequence[SignedResult]) -> GroundedReport:
        """Draft, then at most one redraft, then the template; every result must verify first."""
        if not results:
            raise ValueError("a grounded section needs at least one signed result")
        _table(results)  # refuses two results under one evidence id before the model is asked
        for r in results:
            verify_result(r, key=self._key)
        listing = [
            {
                "evidence_id": r.evidence_id,
                "kind": r.kind,
                "figures": {
                    k: {"placeholder": placeholder(r.evidence_id, k), "value": render(v)}
                    for k, v in r.figures.items()
                },
            }
            for r in results
        ]
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Section: {title}\nSigned results:\n"
                + json.dumps(listing, indent=2, sort_keys=True),
            },
        ]
        rejected: list[str] = []
        for path in ("draft", "redraft"):
            draft = self.llm.chat(messages, temperature=0.2)
            text, links, problems = ground(draft, results)
            if not problems:
                return GroundedReport(title, text, links, path, tuple(rejected))
            rejected += [f"{path}: {p}" for p in problems]
            messages += [
                {"role": "assistant", "content": draft},
                {
                    "role": "user",
                    "content": "The draft was rejected:\n- " + "\n- ".join(problems)
                    + "\nRewrite it with every number as a placeholder from the list.",
                },
            ]
        text, links, problems = ground(template_draft(results), results)
        if problems:  # unreachable: the template only places listed figures
            raise RuntimeError(f"the template is not grounded: {problems}")
        return GroundedReport(title, text, links, "template", tuple(rejected))
