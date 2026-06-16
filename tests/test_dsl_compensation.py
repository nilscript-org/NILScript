"""The DSL becomes a Saga: an action node may declare `compensate_with`, the compensating action
that reverses it when the program unwinds (ROLLBACK). The addition is additive — v0.1 programs that
declare no compensation still validate."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator


def _schema() -> dict[str, Any]:
    path = files("nilscript.dsl") / "schema" / "nilscript-dsl.v0.1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _program(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "wosool": "0.1", "workspace": "ws", "entry": "step_1",
        "pipeline": [{"id": "step_1", "type": "action", "skill": "product",
                      "verb": "commerce.create_product", "args": {"name": "x"}, **action}],
    }


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


def test_action_with_compensate_with_validates() -> None:
    program = _program(
        {"compensate_with": {"verb": "commerce.delete_product",
                             "args": {"product_id": "$.step_1.output.id"}}, "next": None}
    )
    jsonschema.validate(program, _schema())


def test_compensate_with_requires_a_verb() -> None:
    program = _program({"compensate_with": {"args": {}}, "next": None})
    assert not Draft202012Validator(_schema()).is_valid(program)


def test_action_without_compensation_still_validates() -> None:
    jsonschema.validate(_program({"next": None}), _schema())


def test_bundled_compensate_fixture_is_valid() -> None:
    fixture = files("nilscript.dsl") / "conformance" / "valid" / "08-compensate-with.json"
    jsonschema.validate(json.loads(fixture.read_text(encoding="utf-8")), _schema())
