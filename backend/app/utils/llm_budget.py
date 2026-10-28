"""The daily ceiling on live model spend: ``LEDGERWORLD_LLM_DAILY_USD`` (default 5).

Every live model call passes through here: the upstream Chat Completions helper
(``openai_chat_compat.create_chat_completion``) and every camel model backend wrapped by
``budgeted``. Before a call, the day's spend is read from the shared store; once it has reached
the cap the call is refused with ``LLMBudgetExceeded`` and never leaves the process. After a call,
its cost is estimated from the provider's reported token usage (or, when none is reported, from
the text length at four characters a token) and added to the day's total. A scripted model is
free and never metered.

Spend is kept in integer micro-USD per UTC day. The store is Redis at ``REDIS_URL``, shared by the
API, the worker and every simulation subprocess; with no ``REDIS_URL`` the count is this process's
own. A call that is already in flight when the cap is reached still completes, so one round of
concurrent calls can overshoot the cap by their own cost.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

ENV_CAP = "LEDGERWORLD_LLM_DAILY_USD"
DEFAULT_DAILY_USD = "5"
KEY_PREFIX = "ledgerworld:llm:spend"
KEY_TTL_S = 2 * 24 * 3600
CHARS_PER_TOKEN = 4
MICRO = Decimal(1_000_000)

# USD per million tokens (input, output), matched by the longest model-name prefix. A model not
# listed is priced at DEFAULT_PRICE, deliberately high, so an unknown model reaches the cap early
# rather than late.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "gpt-5-mini": (Decimal("0.25"), Decimal("2.00")),
    "gpt-5": (Decimal("1.25"), Decimal("10.00")),
}
DEFAULT_PRICE = (Decimal("2.50"), Decimal("10.00"))


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
        try:
            raw = self.store.get(self._key(day or self._day()))
        except Exception as error:
            raise LLMBudgetUnavailable(
                f"the live model spend store is unreachable ({type(error).__name__}); "
                f"live model calls are refused while {ENV_CAP} cannot be enforced") from error
        return int(raw or 0)

    def check(self) -> None:
        """Refuse a live call once the day's spend has reached the cap."""
        day = self._day()
        cap = self.cap()
        spent = self.spent(day)
        if spent >= cap:
            raise LLMBudgetExceeded(
                f"live model budget reached: {_usd(spent)} spent on {day} (UTC) against "
                f"{ENV_CAP}={_usd(cap)}; live model calls are refused until 00:00 UTC")

    def charge(self, model: str | None, prompt_tokens: int, completion_tokens: int) -> int:
        """Add one call's cost to the day's total and return the new total."""
        key = self._key(self._day())
        total = int(self.store.incrby(key, cost_micro_usd(model, prompt_tokens,
                                                          completion_tokens)))
        self.store.expire(key, KEY_TTL_S)
        return total

    def record(self, model: str | None, messages: Any, response: Any) -> int:
        return self.charge(model, *_usage(response, messages))


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
    """Run one Chat Completions call under the cap, unless ``client`` is scripted."""
    if is_scripted(client):
        return call()
    meter = budget()
    meter.check()
    response = call()
    meter.record(model, messages, response)
    return response


def budgeted(backend: Any) -> Any:
    """Meter a live camel model backend: its ``_run`` and ``_arun`` check and charge the cap."""
    model = str(getattr(backend, "model_type", "") or "")
    run, arun = backend._run, backend._arun

    @functools.wraps(run)
    def _run(messages, *args, **kwargs):
        meter = budget()
        meter.check()
        response = run(messages, *args, **kwargs)
        meter.record(model, messages, response)
        return response

    @functools.wraps(arun)
    async def _arun(messages, *args, **kwargs):
        meter = budget()
        meter.check()
        response = arun(messages, *args, **kwargs)
        if inspect.isawaitable(response):
            response = await response
        meter.record(model, messages, response)
        return response

    backend._run, backend._arun = _run, _arun
    return backend
