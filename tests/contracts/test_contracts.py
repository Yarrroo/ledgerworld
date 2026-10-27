"""Contracts C1–C6: every example, the pydantic models and the JSON Schemas agree (T02)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import get_args

import pytest
from app.finance import schemas
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
MONEY_CASES = ROOT / "prp/2026-10-20-ledgerworld/design/modules/ledger/fixtures/money-cases.json"
EXAMPLES = sorted(CONTRACTS.glob("examples/*/*.json"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def validator(contract: str, def_: str | None = None) -> Draft202012Validator:
    schema = load(CONTRACTS / f"{contract}.schema.json")
    if def_ is not None:
        schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{def_}"}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def schema_errors(check: Draft202012Validator, instance) -> set[tuple[str, str]]:
    """Every (JSON pointer, keyword) a schema raises, including inside anyOf and oneOf."""
    found, todo = set(), list(check.iter_errors(instance))
    while todo:
        error = todo.pop()
        found.add(("".join(f"/{part}" for part in error.absolute_path), error.validator))
        todo.extend(error.context or [])
    return found


def stated(error: dict, path: list, message: str | None) -> bool:
    """A model error is the stated one: at the expected path, or carrying the stated message.

    A model rule reports at the object it checks, not at the field, so an example whose rule
    lives in a validator names the validator's message instead of relying on its location.
    """
    rest = iter(error["loc"])
    at_path = bool(path) and all(part in rest for part in path)
    return at_path or (message is not None and message in error["msg"])


def test_schemas_are_generated_from_the_models():
    for name in schemas.CONTRACTS:
        committed = (CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8")
        assert committed == schemas.contract_text(name), (
            f"contracts/{name}.schema.json drifted: run `uv run python -m app.finance.schemas`"
        )


def test_every_contract_has_a_valid_and_two_invalid_examples():
    for name in schemas.CONTRACTS:
        verdicts = [load(p)["valid"] for p in (CONTRACTS / "examples" / name).glob("*.json")]
        assert verdicts.count(True) >= 1 and verdicts.count(False) >= 2, name


@pytest.mark.parametrize("path", EXAMPLES, ids=[f"{p.parent.name}/{p.stem}" for p in EXAMPLES])
def test_example(path: Path):
    example = load(path)
    contract, def_, instance = path.parent.name, example.get("def"), example["instance"]
    check = validator(contract, def_)
    shape = schemas.C6_MODELS[def_] if def_ else schemas.CONTRACTS[contract]

    if example["valid"]:
        assert schema_errors(check, instance) == set()
        parsed = shape.model_validate(instance)
        assert parsed.model_dump(mode="json", exclude_unset=True) == instance
        dumped = parsed.model_dump(mode="json")
        assert schema_errors(check, dumped) == set()
        assert shape.model_validate(dumped) == parsed
        return

    expected = example["error"]
    assert (expected["path"], expected["keyword"]) in schema_errors(check, instance), (
        example["reason"]
    )
    with pytest.raises(ValidationError) as caught:
        shape.model_validate(instance)
    path_parts = [int(p) if p.isdigit() else p for p in expected["path"].split("/")[1:]]
    message = expected.get("model_message")
    assert any(stated(error, path_parts, message) for error in caught.value.errors()), (
        example["reason"], caught.value.errors(),
    )


def test_money_cases_fixture():
    cases = load(MONEY_CASES)
    check = validator("c5_snapshot", "Money")
    for case in cases["valid"]:
        assert schema_errors(check, case["money"]) == set()
        assert schemas.to_decimal(schemas.Money.model_validate(case["money"])) == case["decimal"]
    for case in cases["invalid"]:
        assert schema_errors(check, case["money"]), case["reason"]
        with pytest.raises(ValidationError):
            schemas.Money.model_validate(case["money"])
    for case in cases["provider_requests"]:
        money = schemas.Money.model_validate(case["leg_amount"])
        if "refused" in case:
            with pytest.raises(ValueError, match=case["refused"]):
                schemas.to_provider_decimal(money)
        else:
            assert schemas.to_provider_decimal(money) == case["request_amount"]


def test_converters_take_money_only():
    with pytest.raises(TypeError):
        schemas.to_provider_decimal(100.5)


def test_provider_boundary_refuses_a_zero_amount():
    with pytest.raises(ValueError, match="zero amount"):
        schemas.to_provider_decimal(schemas.Money(minor=0, currency="USD"))


def test_model_refuses_a_whole_float_that_json_schema_counts_as_integer():
    whole_float = {"minor": 100.0, "currency": "USD"}
    assert schema_errors(validator("c5_snapshot", "Money"), whole_float) == set()
    with pytest.raises(ValidationError):
        schemas.Money.model_validate(whole_float)


def test_minor_units_fit_the_ledger_column():
    biggest = {"minor": 2**63 - 1, "currency": "USD"}
    schemas.Money.model_validate(biggest)
    for minor in (2**63, -(2**63)):
        assert schema_errors(validator("c5_snapshot", "Money"), biggest | {"minor": minor})
        with pytest.raises(ValidationError):
            schemas.Money.model_validate(biggest | {"minor": minor})


def test_times_are_iso_strings_not_epoch_numbers():
    health = example("c6_api", "valid-health")
    assert schema_errors(validator("c6_api", "HealthResponse"), health | {"as_of": 1700000000})
    with pytest.raises(ValidationError):
        schemas.HealthResponse.model_validate(health | {"as_of": 1700000000})


def example(contract: str, name: str):
    return load(CONTRACTS / "examples" / contract / f"{name}.json")["instance"]


def _set(doc, path: str, value):
    *parents, last = [int(p) if p.isdigit() else p for p in path.split(".")]
    for part in parents:
        doc = doc[part]
    doc[last] = value


# A rule JSON Schema cannot state: the schema accepts the instance, the model refuses it.
MODEL_ONLY = [
    ("c5_snapshot", "valid-lf1", {"accounts.0.buckets.reserved.currency": "EUR"},
     "holds USD only"),
    ("c5_snapshot", "valid-lf1", {"obligations.0.account": "borrower-a/elsewhere"},
     "unknown account"),
    ("c5_snapshot", "valid-lf1", {"obligations.0.amount.currency": "EUR"}, "holds USD only"),
    ("c5_snapshot", "valid-lf1", {"exposures.0.flow_id": "nope"}, "unknown flow"),
    ("c5_snapshot", "valid-lf2", {"contracts.0.lender": "ghost"}, "unknown entity"),
    ("c5_snapshot", "valid-lf2", {"contracts.0.reserved_on": "ghost/operating"},
     "unknown account"),
    ("c5_snapshot", "valid-lf2", {"exposures.0.account": "nope"}, "unknown account"),
    ("c5_snapshot", "valid-lf2", {"contracts.1.contract_id": "line-b"}, "repeats"),
    ("c5_snapshot", "valid-lf2", {"contracts.0.drawn.minor": 1000001}, "drawn within"),
    ("c5_snapshot", "valid-lf2", {"contracts.0.drawn.currency": "EUR"}, "drawn within"),
    ("c3_bound_approval", "valid-lf1-integrated", {"legs.1.after": [7]}, "an earlier leg"),
    ("c3_bound_approval", "valid-lf1-integrated", {"legs.0.after": [2]}, "an earlier leg"),
    ("c3_bound_approval", "valid-lf1-integrated",
     {"legs.0.kind": "fx", "legs.0.to_currency": "USD"}, "another currency"),
    ("c4_provider_op", "valid-settled-advance", {"receipt.kind": "payout"}, "another leg"),
    ("c4_provider_op", "valid-settled-advance", {"kind": "payout", "receipt.kind": "payout"},
     "names its kind"),
    ("c5_snapshot", "valid-lf1", {"accounts.0.buckets.pending_in.1.flow_id": "rcv-1"},
     "flow id repeats"),
]


@pytest.mark.parametrize(("contract", "name", "change", "match"), MODEL_ONLY,
                         ids=[f"{c[1]}:{next(iter(c[2]))}" for c in MODEL_ONLY])
def test_model_only_rule(contract: str, name: str, change: dict, match: str):
    instance = example(contract, name)
    for path, value in change.items():
        _set(instance, path, value)
    assert schema_errors(validator(contract), instance) == set()
    with pytest.raises(ValidationError, match=match):
        schemas.CONTRACTS[contract].model_validate(instance)


def test_api_shapes_keep_the_snapshot_rules():
    treasury = {
        "id": "borrower-a/operating", "entity": "borrower-a", "currency": "USD",
        "observability": "known", "as_of": "2026-01-05T00:00:00Z",
        "buckets": {"settled": {"minor": 1, "currency": "USD"},
                    "reserved": {"minor": 0, "currency": "EUR"},
                    "pledged": {"minor": 0, "currency": "USD"}, "pending_in": [],
                    "pending_out": []},
        "spendable": {"minor": 1, "currency": "USD", "status": "known"},
        "authority": "full", "projected": [],
    }
    with pytest.raises(ValidationError, match="holds USD only"):
        schemas.TreasuryAccount.model_validate(treasury)


def test_a_selected_policy_was_evaluated():
    decisions = {
        "as_of": "2026-11-05T10:00:00Z", "mode": "fake", "run_id": "run-1",
        "snapshot_id": "lf1", "checkpoint_round": 3, "cohort": "s1",
        "weight_kind": "unweighted scenario set", "status": "selected", "results": [],
        "selected": "integrated", "escalation": None,
    }
    assert schema_errors(validator("c6_api", "DecisionsResponse"), decisions) == set()
    with pytest.raises(ValidationError, match="was evaluated"):
        schemas.DecisionsResponse.model_validate(decisions)



def test_an_obligation_is_on_its_own_entitys_account():
    snapshot = example("c5_snapshot", "valid-lf1")
    snapshot["entities"].append({"entity_id": "borrower-b", "name": "Juniper Freight (synthetic)",
                                 "kind": "borrower"})
    snapshot["obligations"][0]["entity"] = "borrower-b"
    with pytest.raises(ValidationError, match="not owned by borrower-b"):
        schemas.Snapshot.model_validate(snapshot)


def test_a_line_is_reserved_on_its_lenders_account():
    snapshot = example("c5_snapshot", "valid-lf2")
    snapshot["accounts"].append({
        "id": "borrower-a/operating", "entity": "borrower-a", "currency": "USD",
        "observability": "known", "as_of": "2026-01-05T00:00:00Z",
        "buckets": {"settled": {"minor": 1, "currency": "USD"},
                    "reserved": {"minor": 0, "currency": "USD"},
                    "pledged": {"minor": 0, "currency": "USD"}, "pending_in": [],
                    "pending_out": []}})
    snapshot["contracts"][0]["reserved_on"] = "borrower-a/operating"
    with pytest.raises(ValidationError, match="the lender's account"):
        schemas.Snapshot.model_validate(snapshot)


def test_pool_entities_are_unique():
    snapshot = example("c5_snapshot", "valid-lf2")
    snapshot["pools"].append(snapshot["pools"][0])
    with pytest.raises(ValidationError, match="pool id repeats"):
        schemas.Snapshot.model_validate(snapshot)


def treasury_account(**change):
    account = {
        "id": "lender/venue", "entity": "lender", "currency": "USD",
        "observability": "unknown", "as_of": "2026-01-05T00:00:00Z",
        "buckets": {"settled": None, "reserved": {"minor": 0, "currency": "USD"},
                    "pledged": {"minor": 0, "currency": "USD"}, "pending_in": [],
                    "pending_out": []},
        "floor": {"minor": None, "currency": "USD", "status": "unassessed"},
        "spendable": {"minor": None, "currency": "USD", "status": "unknown"},
        "authority": "reduced", "projected": [],
    }
    return account | change


def test_treasury_floor_is_a_metric():
    schemas.TreasuryAccount.model_validate(treasury_account())


def test_an_unknown_account_has_reduced_authority():
    check = validator("c6_api", "TreasuryAccount")
    for bad in (treasury_account(authority="full"),
                treasury_account(spendable={"minor": 5000, "currency": "USD",
                                            "status": "known"})):
        assert schema_errors(check, bad)
        with pytest.raises(ValidationError, match="reduced authority"):
            schemas.TreasuryAccount.model_validate(bad)


def test_a_selected_policy_is_feasible_on_every_scenario():
    result = {"policy": "no-action", "scenario_id": "s1", "branch_id": "run-1-s1-no-action",
              "replay": False, "obligations_unmet": 0, "floor_kept": False,
              "min_cash": {"minor": 2000000, "currency": "USD", "status": "known"},
              "funding_cost": {"minor": 0, "currency": "USD"}, "feasible": False}
    decisions = {
        "as_of": "2026-11-05T10:00:00Z", "mode": "fake", "run_id": "run-1",
        "snapshot_id": "lf1", "checkpoint_round": 3, "cohort": "s1",
        "weight_kind": "unweighted scenario set", "status": "selected", "results": [result],
        "selected": "no-action", "escalation": None,
    }
    with pytest.raises(ValidationError, match="feasible on every scenario"):
        schemas.DecisionsResponse.model_validate(decisions)
    schemas.DecisionsResponse.model_validate(
        decisions | {"results": [result | {"feasible": True, "floor_kept": True}]})


def test_contract_kinds_match_the_snapshot_union():
    kinds = {model.model_fields["kind"].annotation.__args__[0]
             for model in (schemas.CommittedLine, schemas.RevenueAdvance,
                           schemas.CollateralFacility)}
    assert kinds == set(get_args(schemas.ContractKind))
