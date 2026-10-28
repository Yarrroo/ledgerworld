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
    # json of MESSAGES is 38 chars: 10 tokens at the default $15 per million input tokens
    assert int(shared.get("ledgerworld:llm:spend:2026-10-28")) == 150


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
        def incrby(self, key, amount):
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
    assert cost_micro_usd("meta-llama/Llama-4-Maverick-17B", 1_000_000, 0) == 1_000_000
    # a dearer member of a priced family is not priced as the family
    assert cost_micro_usd("gpt-5-pro", 1_000_000, 0) == 15_000_000
    assert cost_micro_usd("gpt-4-turbo", 1_000_000, 0) == 10_000_000
    assert cost_micro_usd("o1", 0, 1_000_000) == 60_000_000
    assert cost_micro_usd("some-new-model", 1_000_000, 1_000_000) == 135_000_000


def test_concurrent_calls_hold_the_cap_before_any_returns(shared):
    # A round of agents calls at once: each holds its prompt's cost before answering, so only
    # the calls that fit under the $1 cap reach the model.
    started = 0

    class Backend(FakeBackend):
        async def _arun(self, messages, response_format=None, tools=None):
            nonlocal started
            started += 1
            await asyncio.sleep(0.01)
            return self._response()

    big = [{"role": "user", "content": "x" * 4_000_000}]  # ~1M tokens, $0.15 held each

    async def round_():
        backends = [budgeted(Backend()) for _ in range(20)]
        return await asyncio.gather(*(b._arun(big) for b in backends), return_exceptions=True)

    results = asyncio.run(round_())
    refused = [r for r in results if isinstance(r, LLMBudgetExceeded)]
    assert started == 7 and len(refused) == 13


def test_a_failed_call_gives_its_hold_back(shared):
    class Failing(FakeModelClient):
        def _create(self, **kwargs):
            raise TimeoutError("provider timed out")

    with pytest.raises(TimeoutError):
        call(Failing())
    assert int(shared.get("ledgerworld:llm:spend:2026-10-28")) == 0


def test_a_paid_response_is_returned_when_its_cost_cannot_be_written(clock):
    class Flaky:
        def __init__(self):
            self.value, self.calls = 0, 0

        def incrby(self, key, amount):
            self.calls += 1
            if self.calls > 1:
                raise ConnectionError("down")
            self.value += amount
            return self.value

        def expire(self, key, seconds):
            return True

    previous = llm_budget.use_budget(LLMBudget(Flaky(), cap_micro_usd=1_000_000, clock=clock))
    try:
        client = FakeModelClient()
        assert call(client).usage is client.usage
        assert client.calls == 1
    finally:
        llm_budget.use_budget(previous)


def test_the_profile_generator_stops_at_the_cap_instead_of_retrying(shared, monkeypatch):
    from app.services import oasis_profile_generator as gen

    shared.set("ledgerworld:llm:spend:2026-10-28", 1_000_000)
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("a refused call was retried"))
    generator = gen.OasisProfileGenerator(api_key="test-not-a-key", zep_api_key="")
    generator.client = FakeModelClient()
    with pytest.raises(LLMBudgetExceeded):
        generator._generate_profile_with_llm("Ada", "person", "a lender", {}, "")
    assert generator.client.calls == 0


def test_the_config_generator_stops_at_the_cap_instead_of_retrying(shared, monkeypatch):
    from app.services import simulation_config_generator as gen

    shared.set("ledgerworld:llm:spend:2026-10-28", 1_000_000)
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("a refused call was retried"))
    generator = gen.SimulationConfigGenerator(api_key="test-not-a-key")
    generator.client = FakeModelClient()
    with pytest.raises(LLMBudgetExceeded):
        generator._call_llm_with_retry("prompt", "system")


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
