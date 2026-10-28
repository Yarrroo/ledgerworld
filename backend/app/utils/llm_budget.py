"""The daily ceiling on live model spend: ``LEDGERWORLD_LLM_DAILY_USD`` (default 5).

Every live model call passes through here: the upstream Chat Completions helper
(``openai_chat_compat.create_chat_completion``) and every camel model backend wrapped by
``budgeted``. Before a call, the prompt's estimated cost is held against the day's spend in the
shared store; when the spend before that hold, other calls' holds included, has reached the cap,
the call is refused with ``LLMBudgetExceeded`` and never leaves the process. After a call, the
hold is replaced by its cost from the provider's reported token usage (or, when none is reported,
from the text length at four characters a token); a call that fails gives its hold back. A
scripted model is free and never metered.

Spend is kept in integer micro-USD per UTC day. The store is Redis at ``REDIS_URL``, shared by the
API, the worker and every simulation subprocess; with no ``REDIS_URL`` the count is this process's
own. Because a hold covers the prompt only, calls admitted together can overshoot the cap by their
completions' cost. A response already paid for is always returned, even when its cost cannot be
written back.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import threading
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

ENV_CAP = "LEDGERWORLD_LLM_DAILY_USD"
DEFAULT_DAILY_USD = "5"
KEY_PREFIX = "ledgerworld:llm:spend"
KEY_TTL_S = 2 * 24 * 3600
CHARS_PER_TOKEN = 4
MICRO = Decimal(1_000_000)

logger = logging.getLogger(__name__)

# USD per million tokens (input, output), matched by the longest model-name prefix after any
# "provider/" part. A model not listed is priced at DEFAULT_PRICE, the top of the market, so an
# unknown model reaches the cap early rather than late. A family prefix carries the price of its
# dearest common member.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4-turbo": (Decimal("10.00"), Decimal("30.00")),
    "gpt-4": (Decimal("30.00"), Decimal("60.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "gpt-5-mini": (Decimal("0.25"), Decimal("2.00")),
    "gpt-5-pro": (Decimal("15.00"), Decimal("120.00")),
    "gpt-5": (Decimal("1.25"), Decimal("10.00")),
    "o1-mini": (Decimal("1.10"), Decimal("4.40")),
    "o1": (Decimal("15.00"), Decimal("60.00")),
    "o3-mini": (Decimal("1.10"), Decimal("4.40")),
    "o3": (Decimal("2.00"), Decimal("8.00")),
    "o4-mini": (Decimal("1.10"), Decimal("4.40")),
    "claude-haiku": (Decimal("1.00"), Decimal("5.00")),
    "claude-sonnet": (Decimal("3.00"), Decimal("15.00")),
    "claude-opus": (Decimal("15.00"), Decimal("75.00")),
    "llama": (Decimal("1.00"), Decimal("3.00")),
}
DEFAULT_PRICE = (Decimal("15.00"), Decimal("120.00"))


class LLMBudgetExceeded(RuntimeError):
    """A live model call refused because the day's spend has reached the cap."""


class LLMBudgetUnavailable(LLMBudgetExceeded):
    """A live model call refused because the cap or the day's spend cannot be read."""


def price(model: str | None) -> tuple[Decimal, Decimal]:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    best = max((p for p in PRICES if name.startswith(p)), key=len, default=None)
    return PRICES[best] if best else DEFAULT_PRICE


def cost_micro_usd(model: str | None, prompt_tokens: int, completion_tokens: int) -> int:
    """The estimated cost of one call, rounded up to a whole micro-USD."""
    p_in, p_out = price(model)
    # USD per million tokens is micro-USD per token.
    cost = p_in * prompt_tokens + p_out * completion_tokens
    return int(cost.to_integral_value(rounding=ROUND_CEILING))


def daily_cap_micro_usd(env: Mapping[str, str] | None = None) -> int:
    raw = (env if env is not None else os.environ).get(ENV_CAP, "").strip() or DEFAULT_DAILY_USD
    try:
        usd = Decimal(raw)
    except InvalidOperation:
        usd = Decimal("NaN")
    if not usd.is_finite() or usd < 0:
        raise LLMBudgetUnavailable(f"{ENV_CAP}={raw!r} is not a non-negative number of USD; "
                                   "live model calls are refused until it is")
    return int((usd * MICRO).to_integral_value(rounding=ROUND_CEILING))


def _usd(micro: int) -> str:
    return f"${Decimal(micro) / MICRO:.2f}"


class _LocalStore:
    """The day's count for one process, when no shared store is configured."""

    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> int | None:
        with self._lock:
            return self._values.get(key)

    def incrby(self, key: str, amount: int) -> int:
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount
            return self._values[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True


def _tokens(value: Any) -> str:
    """The text of a message list or a response, for a length-based token estimate."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _estimate(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def _usage(response: Any, messages: Any) -> tuple[int, int]:
    """(prompt, completion) tokens: the provider's count, or an estimate from the text."""
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if isinstance(prompt, int) and isinstance(completion, int):
        return prompt, completion
    from .openai_chat_compat import extract_chat_completion_text

    return _estimate(_tokens(messages)), _estimate(extract_chat_completion_text(response))


class LLMBudget:
    """The day's live model spend in ``store`` (a Redis client or alike), against the cap."""

    def __init__(self, store: Any = None, *, cap_micro_usd: int | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.store = store if store is not None else _LocalStore()
        self.cap_micro_usd = cap_micro_usd
        self.clock = clock

    def _day(self) -> str:
        return self.clock().astimezone(UTC).date().isoformat()

    def _key(self, day: str) -> str:
        return f"{KEY_PREFIX}:{day}"

    def cap(self) -> int:
        return self.cap_micro_usd if self.cap_micro_usd is not None else daily_cap_micro_usd()

    def spent(self, day: str | None = None) -> int:
        return int(self.store.get(self._key(day or self._day())) or 0)

    def reserve(self, model: str | None, messages: Any) -> tuple[str, int]:
        """Hold the prompt's estimated cost before a call, or refuse the call at the cap.

        Returns the day's key and the hold, for ``settle`` or ``release``.
        """
        day = self._day()
        key = self._key(day)
        cap = self.cap()
        hold = cost_micro_usd(model, _estimate(_tokens(messages)), 0)
        try:
            total = int(self.store.incrby(key, hold))
            self.store.expire(key, KEY_TTL_S)
        except Exception as error:
            raise LLMBudgetUnavailable(
                f"the live model spend store is unreachable ({type(error).__name__}); "
                f"live model calls are refused while {ENV_CAP} cannot be enforced") from error
        before = total - hold
        if before >= cap:
            self.release(key, hold)
            raise LLMBudgetExceeded(
                f"live model budget reached: {_usd(before)} spent on {day} (UTC) against "
                f"{ENV_CAP}={_usd(cap)}; live model calls are refused until 00:00 UTC")
        return key, hold

    def _adjust(self, key: str, amount: int) -> None:
        """Best effort, after the call: a store error is logged, never raised over a response."""
        try:
            self.store.incrby(key, amount)
        except Exception as error:  # noqa: BLE001 — any store failure: the response stands
            logger.warning("live model spend not written back (%s): %d micro-USD on %s",
                           type(error).__name__, amount, key)

    def release(self, key: str, hold: int) -> None:
        """Give back the hold of a call that was refused or failed."""
        if hold:
            self._adjust(key, -hold)

    def settle(self, key: str, hold: int, model: str | None, messages: Any, response: Any) -> int:
        """Replace a call's hold by its cost, and return the cost."""
        cost = cost_micro_usd(model, *_usage(response, messages))
        if cost != hold:
            self._adjust(key, cost - hold)
        return cost


_budget: LLMBudget | None = None
_budget_lock = threading.Lock()


def budget() -> LLMBudget:
    """The process's budget, on Redis at ``REDIS_URL`` when it is set."""
    global _budget
    with _budget_lock:
        if _budget is None:
            url = os.environ.get("REDIS_URL")
            if url:
                import redis

                _budget = LLMBudget(redis.Redis.from_url(url))
            else:
                _budget = LLMBudget()
        return _budget


def use_budget(new: LLMBudget | None) -> LLMBudget | None:
    """Install ``new`` as the process's budget (None: rebuild from the environment next call)."""
    global _budget
    with _budget_lock:
        old, _budget = _budget, new
        return old


def is_scripted(client: Any) -> bool:
    return bool(getattr(client, "scripted", False))


def metered(client: Any, model: str | None, messages: Any, call: Callable[[], Any]) -> Any:
    """Run one model call under the cap, unless ``client`` is scripted."""
    if is_scripted(client):
        return call()
    meter = budget()
    key, hold = meter.reserve(model, messages)
    try:
        response = call()
    except BaseException:
        meter.release(key, hold)
        raise
    meter.settle(key, hold, model, messages, response)
    return response


async def ametered(client: Any, model: str | None, messages: Any,
                   call: Callable[[], Awaitable[Any]]) -> Any:
    """``metered`` for an awaitable call."""
    if is_scripted(client):
        return await call()
    meter = budget()
    key, hold = meter.reserve(model, messages)
    try:
        response = await call()
    except BaseException:
        meter.release(key, hold)
        raise
    meter.settle(key, hold, model, messages, response)
    return response


def budgeted(backend: Any) -> Any:
    """Meter a live camel model backend: its ``_run`` and ``_arun`` are held to the cap."""
    model = str(getattr(backend, "model_type", "") or "")
    run, arun = backend._run, backend._arun

    @functools.wraps(run)
    def _run(messages, *args, **kwargs):
        return metered(backend, model, messages, lambda: run(messages, *args, **kwargs))

    @functools.wraps(arun)
    async def _arun(messages, *args, **kwargs):
        return await ametered(backend, model, messages, lambda: arun(messages, *args, **kwargs))

    backend._run, backend._arun = _run, _arun
    return backend
