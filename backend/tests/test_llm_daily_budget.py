"""LEDGERWORLD_LLM_DAILY_USD caps live model spend per UTC day, in the shared store."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import fakeredis
import pytest
from app.utils import llm_budget
from app.utils.llm_budget import (
    LLMBudget,
    LLMBudgetExceeded,
    LLMBudgetUnavailable,
    budgeted,
    cost_micro_usd,
    daily_cap_micro_usd,
)
from app.utils.openai_chat_compat import create_chat_completion

MESSAGES = [{"role": "user", "content": "hello"}]


class FakeModelClient:
    """A live-looking OpenAI client: every call is answered and reports its token usage."""

    def __init__(self, prompt_tokens=1_000_000, completion_tokens=0):
        self.calls = 0
        self.usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                                     completion_tokens=completion_tokens)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(choices=[], usage=self.usage)


class Clock:
    def __init__(self, when):
        self.when = when

    def __call__(self):
        return self.when


@pytest.fixture
def clock():
    return Clock(datetime(2026, 10, 28, 12, tzinfo=UTC))


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.fixture
def shared(redis, clock, monkeypatch):
    """The process budget on a shared (fake) Redis, with the env cap at $1."""
    monkeypatch.setenv("LEDGERWORLD_LLM_DAILY_USD", "1")
    previous = llm_budget.use_budget(LLMBudget(redis, clock=clock))
    yield redis
    llm_budget.use_budget(previous)


def call(client, model="gpt-4o-mini"):
    return create_chat_completion(client, model=model, messages=MESSAGES)


def test_live_calls_are_refused_once_the_day_cap_is_reached(shared):
    # gpt-4o-mini input is $0.15 per million tokens: a $1 cap admits 7 calls of a million.
    client = FakeModelClient()
    for _ in range(7):
        call(client)
    with pytest.raises(LLMBudgetExceeded, match="LEDGERWORLD_LLM_DAILY_USD"):
        call(client)
    assert client.calls == 7  # the refused call never reached the client


def test_spend_is_kept_per_utc_day_in_the_shared_store(shared, clock):
    client = FakeModelClient()
    call(client)
    assert int(shared.get("ledgerworld:llm:spend:2026-10-28")) == 150_000
    assert shared.ttl("ledgerworld:llm:spend:2026-10-28") > 0
    # another process on the same store sees the same day's total
    other = LLMBudget(shared, clock=clock)
    assert other.spent() == 150_000

    shared.set("ledgerworld:llm:spend:2026-10-28", 1_000_000)
    with pytest.raises(LLMBudgetExceeded):
        call(client)
    clock.when = datetime(2026, 10, 29, 0, 0, 1, tzinfo=UTC)
    call(client)
    assert client.calls == 2


def test_scripted_clients_are_free(shared):
    shared.set("ledgerworld:llm:spend:2026-10-28", 10_000_000)
    scripted = FakeModelClient()
    scripted.scripted = True
    call(scripted)
    assert scripted.calls == 1
    assert int(shared.get("ledgerworld:llm:spend:2026-10-28")) == 10_000_000


def test_the_scripted_model_client_is_marked_free():
    from app.testing.scripted_model import ScriptedPlan

    plan = ScriptedPlan([{"default": True, "content": "ok"}])
    assert llm_budget.is_scripted(plan.model("a", lambda: 0).openai_client())


def test_a_response_without_usage_is_estimated_from_its_text(shared):
    client = FakeModelClient()
    client.usage = None
    call(client, model="unknown-model")
    # json of MESSAGES is 38 chars: 10 tokens at the default $2.50 per million input tokens
    assert int(shared.get("ledgerworld:llm:spend:2026-10-28")) == 25


def test_cap_defaults_to_five_dollars_and_rejects_nonsense():
    assert daily_cap_micro_usd({}) == 5_000_000
    assert daily_cap_micro_usd({"LEDGERWORLD_LLM_DAILY_USD": ""}) == 5_000_000
    assert daily_cap_micro_usd({"LEDGERWORLD_LLM_DAILY_USD": "0.5"}) == 500_000
    for bad in ("-1", "five", "nan", "inf"):
        with pytest.raises(LLMBudgetUnavailable):
            daily_cap_micro_usd({"LEDGERWORLD_LLM_DAILY_USD": bad})


def test_a_zero_cap_refuses_every_live_call(shared, monkeypatch):
    monkeypatch.setenv("LEDGERWORLD_LLM_DAILY_USD", "0")
    client = FakeModelClient()
    with pytest.raises(LLMBudgetExceeded):
        call(client)
    assert client.calls == 0


def test_an_unreachable_store_refuses_live_calls(clock, monkeypatch):
    class Down:
        def get(self, key):
            raise ConnectionError("down")

    previous = llm_budget.use_budget(LLMBudget(Down(), clock=clock))
    try:
        client = FakeModelClient()
        with pytest.raises(LLMBudgetUnavailable):
            call(client)
        assert client.calls == 0
    finally:
        llm_budget.use_budget(previous)


def test_prices_round_up_and_unknown_models_are_priced_high():
    assert cost_micro_usd("gpt-4o-mini", 1, 0) == 1  # 0.15 micro-USD rounds up
    assert cost_micro_usd("openai/gpt-4o-mini", 1_000_000, 1_000_000) == 750_000
    assert cost_micro_usd("gpt-4o", 1_000_000, 0) == 2_500_000
    assert cost_micro_usd("Llama-4-Maverick", 1_000_000, 0) == 2_500_000


class FakeBackend:
    """A camel model backend's private run methods, as ``budgeted`` sees them."""

    model_type = "gpt-4o-mini"

    def __init__(self):
        self.calls = 0

    def _response(self):
        self.calls += 1
        return SimpleNamespace(choices=[], usage=SimpleNamespace(
            prompt_tokens=1_000_000, completion_tokens=0))

    def _run(self, messages, response_format=None, tools=None):
        return self._response()

    async def _arun(self, messages, response_format=None, tools=None):
        return self._response()


def test_budgeted_camel_backends_are_metered(shared):
    backend = budgeted(FakeBackend())
    for _ in range(4):
        backend._run(MESSAGES)
    for _ in range(3):
        asyncio.run(backend._arun(MESSAGES))
    with pytest.raises(LLMBudgetExceeded):
        backend._run(MESSAGES)
    with pytest.raises(LLMBudgetExceeded):
        asyncio.run(backend._arun(MESSAGES))
    assert backend.calls == 7


def test_the_demo_live_model_is_budgeted(shared, monkeypatch):
    from app.demo.run import model_factory

    monkeypatch.setenv("LLM_API_KEY", "test-not-a-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-4o-mini")
    shared.set("ledgerworld:llm:spend:2026-10-28", 1_000_000)
    model = model_factory("live")("actor", None)
    with pytest.raises(LLMBudgetExceeded):
        model.run(MESSAGES)
