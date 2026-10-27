"""Grounded reports: every number in the prose comes from a signed structured result.

g2 `report_numbers_grounded` (system brief §13: no fabricated comparison, receipt or probability).
A structured result is a set of named figures (Money or an integer count) under one evidence id,
signed with HMAC-SHA256 by whoever produced it; the key is the caller's, never the model's.

The model writes each figure as a placeholder ``{{<evidence_id>#<figure>}}`` and the placeholder
is filled with the figure's rendered value. Any other number in the prose must equal a figure's
value, and is then linked to every figure carrying that value; a number in no result, or a
placeholder naming no figure, rejects the draft. A rejected draft gets one redraft with the
reasons; a rejected redraft gives way to a template written from the results alone. Every number
in the returned text lies inside a link to an evidence id, on all three paths.

A number is any run of digits, so an identifier like ``LF-1`` or ``round 4`` in the prose counts
and fails unless a result carries it. Figure and kind names hold no digit for the same reason: the
template prints them. Numbers spelt as words are not detected.

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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from app.finance.schemas import Money, Sha256, to_decimal
from app.services.report_agent import ReportAgent

EvidenceId = Annotated[str, StringConstraints(pattern=r"^[^\s{}#]{1,128}$")]
# Printed by the template, so a digit here would be a number no result carries.
Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,63}$")]
Figure = Money | StrictInt

PLACEHOLDER = re.compile(r"\{\{\s*([^\s{}#]+)#([^\s{}#]+)\s*\}\}")
# Grouped thousands or plain digits with an optional fraction; a minus only where it is not a
# hyphen inside a word (in "LF-1" the number is 1).
NUMBER = re.compile(r"(?:(?<!\w)-)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")

SYSTEM_PROMPT = (
    "You write one section of a treasury simulation report from signed structured results. "
    "Write every number as a placeholder {{<evidence_id>#<figure>}} naming a figure listed "
    "below; it is replaced with the figure's value. Write no other digits: no dates, rounds, "
    "identifiers, percentages or estimates. Never invent a comparison, receipt or probability."
)


class UnverifiedResult(ValueError):
    """A structured result whose signature does not match its content under the key."""


class SignedResult(BaseModel):
    """Named figures under one evidence id, with the HMAC-SHA256 of their canonical form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: EvidenceId
    kind: Label
    figures: Annotated[dict[Label, Figure], Field(min_length=1)]
    signature: Sha256


def _payload(evidence_id: str, kind: str, figures: dict[str, Figure]) -> bytes:
    body = {
        "evidence_id": evidence_id,
        "kind": kind,
        "figures": {
            k: v.model_dump() if isinstance(v, Money) else v for k, v in figures.items()
        },
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _mac(key: bytes, payload: bytes) -> str:
    if not isinstance(key, bytes) or not key:
        raise ValueError("a signing key is non-empty bytes")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def sign_result(
    evidence_id: str, kind: str, figures: dict[str, Any], *, key: bytes
) -> SignedResult:
    """Validate the figures (Money or int, never a float) and sign them under ``evidence_id``."""
    unsigned = SignedResult(
        evidence_id=evidence_id, kind=kind, figures=figures, signature="0" * 64
    )
    mac = _mac(key, _payload(unsigned.evidence_id, unsigned.kind, unsigned.figures))
    return unsigned.model_copy(update={"signature": mac})


def verify_result(result: SignedResult, *, key: bytes) -> SignedResult:
    """The result itself, or ``UnverifiedResult`` when its content is not what was signed."""
    expected = _mac(key, _payload(result.evidence_id, result.kind, result.figures))
    if not hmac.compare_digest(expected, result.signature):
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
    """A span of the report text and the figures it was filled from or matches."""

    start: int
    end: int
    text: str
    refs: tuple[FigureRef, ...]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.evidence_id for r in self.refs))


@dataclass(frozen=True)
class GroundedReport:
    title: str
    text: str
    links: tuple[NumberLink, ...]
    path: Literal["draft", "redraft", "template"]
    rejected: tuple[str, ...]  # why each failed attempt was refused, oldest first

    def unlinked(self) -> list[str]:
        """Numbers in the text that no link covers; empty for every report this module returns."""
        return [
            m.group()
            for m in NUMBER.finditer(self.text)
            if not any(ln.start <= m.start() and m.end() <= ln.end for ln in self.links)
        ]


def ground(
    draft: str, results: Sequence[SignedResult]
) -> tuple[str, tuple[NumberLink, ...], list[str]]:
    """Fill the draft's placeholders and link its numbers: (text, links, problems).

    The text is usable only when ``problems`` is empty.
    """
    table = {
        FigureRef(r.evidence_id, k): v for r in results for k, v in r.figures.items()
    }
    by_amount: dict[Decimal, list[FigureRef]] = {}
    for ref, value in table.items():
        by_amount.setdefault(_amount(value), []).append(ref)

    out: list[str] = []
    links: list[NumberLink] = []
    problems: list[str] = []
    length = 0

    def emit(text: str, refs: tuple[FigureRef, ...] | None) -> None:
        nonlocal length
        if refs is not None:
            links.append(NumberLink(length, length + len(text), text, refs))
        out.append(text)
        length += len(text)

    def prose(segment: str) -> None:
        if "{{" in segment or "}}" in segment:
            problems.append(f"a malformed placeholder in {segment.strip()[:80]!r}")
        pos = 0
        for m in NUMBER.finditer(segment):
            emit(segment[pos:m.start()], None)
            refs = by_amount.get(Decimal(m.group().replace(",", "")))
            if refs is None:
                problems.append(f"the number {m.group()} is in no signed result")
            emit(m.group(), tuple(refs or ()))
            pos = m.end()
        emit(segment[pos:], None)

    if not draft.strip():
        problems.append("the draft is empty")
    pos = 0
    for m in PLACEHOLDER.finditer(draft):
        prose(draft[pos:m.start()])
        ref = FigureRef(m.group(1), m.group(2))
        if ref in table:
            emit(render(table[ref]), (ref,))
        else:
            problems.append(f"the placeholder {m.group()} names no figure of a signed result")
            emit(m.group(), ())
        pos = m.end()
    prose(draft[pos:])
    return "".join(out), tuple(ln for ln in links if ln.refs), problems


def template_draft(results: Sequence[SignedResult]) -> str:
    """The fallback section: one sentence per result, every figure a placeholder."""
    lines = []
    for r in results:
        parts = "; ".join(
            f"{k.replace('_', ' ')} {{{{{r.evidence_id}#{k}}}}}" for k in r.figures
        )
        lines.append(f"{r.kind.replace('_', ' ').capitalize()}: {parts}.")
    return "\n".join(lines)


class _NoGraphMemory:
    """Stands in for the upstream graph tools: a grounded section never reads graph memory."""

    def __getattr__(self, name: str) -> Any:
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
        zep_tools=None,
    ) -> None:
        super().__init__(
            graph_id,
            simulation_id,
            simulation_requirement,
            llm_client=llm_client,
            zep_tools=zep_tools or _NoGraphMemory(),
        )
        self._key = key

    def write_section(self, title: str, results: Sequence[SignedResult]) -> GroundedReport:
        """Draft, then at most one redraft, then the template; every result must verify first."""
        if not results:
            raise ValueError("a grounded section needs at least one signed result")
        for r in results:
            verify_result(r, key=self._key)
        listing = [
            {
                "evidence_id": r.evidence_id,
                "kind": r.kind,
                "figures": {
                    k: {"placeholder": f"{{{{{r.evidence_id}#{k}}}}}", "value": render(v)}
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
            rejected.extend(f"{path}: {p}" for p in problems)
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
