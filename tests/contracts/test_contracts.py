"""Contracts C1–C6: every example, the pydantic models and the JSON Schemas agree (T02)."""

from __future__ import annotations

import json
from pathlib import Path

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


def validator(contract: str, def_: str | None = None) -> Draft202012Validator:
    schema = load(CONTRACTS / f"{contract}.schema.json")
    if def_ is not None:
        schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{def_}"}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def model(contract: str, def_: str | None = None):
    return schemas.C6_MODELS[def_] if def_ else schemas.CONTRACTS[contract]


def schema_errors(check: Draft202012Validator, instance) -> set[tuple[str, str]]:
    """Every (JSON pointer, keyword) a schema raises, including inside anyOf and oneOf."""
    found, todo = set(), list(check.iter_errors(instance))
    while todo:
        error = todo.pop()
        found.add(("".join(f"/{part}" for part in error.absolute_path), error.validator))
        todo.extend(error.context or [])
    return found


def located(expected: list, loc: tuple) -> bool:
    """A model error sits at the expected path, or at the object a model rule checks."""
    rest = iter(loc)
    return all(part in rest for part in expected) or list(loc) == expected[: len(loc)]


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


def test_every_route_names_shapes_the_api_schema_defines():
    defs = load(CONTRACTS / "c6_api.schema.json")["$defs"]
    for route, shape in schemas.C6_ROUTES.items():
        assert shape["response"] in defs, route
        assert shape["request"] is None or shape["request"] in defs, route


@pytest.mark.parametrize("path", EXAMPLES, ids=[f"{p.parent.name}/{p.stem}" for p in EXAMPLES])
def test_example(path: Path):
    example = load(path)
    contract, def_, instance = path.parent.name, example.get("def"), example["instance"]
    check, shape = validator(contract, def_), model(contract, def_)

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
    want = [int(p) if p.isdigit() else p for p in expected["path"].split("/")[1:]]
    assert any(located(want, error["loc"]) for error in caught.value.errors()), (
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


def test_model_refuses_a_whole_float_that_json_schema_counts_as_integer():
    whole_float = {"minor": 100.0, "currency": "USD"}
    assert schema_errors(validator("c5_snapshot", "Money"), whole_float) == set()
    with pytest.raises(ValidationError):
        schemas.Money.model_validate(whole_float)


def example(contract: str, name: str):
    return load(CONTRACTS / "examples" / contract / f"{name}.json")["instance"]


def model_only(contract: str, instance, match: str):
    """A rule JSON Schema cannot state: the schema accepts, the model refuses."""
    assert schema_errors(validator(contract), instance) == set()
    with pytest.raises(ValidationError, match=match):
        schemas.CONTRACTS[contract].model_validate(instance)


def test_model_only_rules():
    snapshot = example("c5_snapshot", "valid-lf1")
    snapshot["accounts"][0]["buckets"]["reserved"]["currency"] = "EUR"
    model_only("c5_snapshot", snapshot, "holds USD only")

    snapshot = example("c5_snapshot", "valid-lf1")
    snapshot["obligations"][0]["account"] = "borrower-a/elsewhere"
    model_only("c5_snapshot", snapshot, "unknown account")

    approval = example("c3_bound_approval", "valid-lf1-integrated")
    approval["legs"][1]["after"] = [7]
    model_only("c3_bound_approval", approval, "not another leg")

    op = example("c4_provider_op", "valid-settled-advance")
    op["receipt"]["kind"] = "payout"
    model_only("c4_provider_op", op, "another leg")
