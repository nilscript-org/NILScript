"""The `.capability.nil` parser — `parse_capability_nil(text) -> Capability`, the exact inverse of
`nil_printer.print_capability_nil`.

Reuses the cycle grammar family's tokenizer and reader base (`cycle/nil_parser.py`) — one lexical
convention across every `.nil` object. The parser's only job is shape; `Capability.model_validate`
is the law (closed objects, the archetype enum, the "default" implementation rule, id patterns), so
an invalid capability refuses with a structured `NilSyntaxError(message, line, col)` — never a bare
pydantic traceback.
"""

from __future__ import annotations

from typing import Any

from nilscript.capability.models import Capability
from nilscript.cycle.nil_parser import (
    NilSyntaxError,
    _as_bilingual,
    _Reader,
    _tokenize,
)


class _CapabilityReader(_Reader):
    def capability(self) -> dict[str, Any]:
        self._expect_word("capability")
        capability_id = self._word()
        version_tok = self._peek()
        version = self._word()
        if not version.startswith("v") or len(version) < 2:
            self._fail(f"expected a version like v2.3 but found {version!r}", version_tok)
        self._expect_punct("{")
        raw: dict[str, Any] = {
            "nil": "capability/0.1",
            "capability_id": capability_id,
            "version": version[1:],
        }
        self._body(raw)
        self._expect_punct("}")
        if self._peek().kind != "eof":
            self._fail(f"unexpected trailing token {self._peek().value!r}")
        return raw

    def _body(self, raw: dict[str, Any]) -> None:
        while not self._is_punct("}"):
            tok = self._peek()
            if tok.kind != "word":
                self._fail(f"expected a section keyword but found {tok.value!r}", tok)
            kw = tok.value
            self._next()
            if kw == "workspace":
                raw["workspace"] = self._string()
            elif kw == "domain":
                raw["domain"] = self._word()
            elif kw == "owner":
                self._expect_word("role")
                raw["owner_role"] = self._word()
            elif kw == "intent":
                raw["intent"] = _as_bilingual(self._bilingual())
            elif kw in ("aliases", "examples"):
                raw[kw] = self._phrase_block()
            elif kw in ("inputs", "outputs"):
                raw[kw] = self._fields_block()
            elif kw == "risk":
                raw["risk"] = self._word()
            elif kw == "strategy":
                raw["strategy"] = self._word()
            elif kw == "compensation":
                raw["compensation"] = self._word()
            elif kw in ("requires", "creates", "enables"):
                raw[kw] = self._id_list()
            elif kw == "exposure":
                raw["exposure"] = self._exposure()
            elif kw == "sod":
                raw["sod"] = self._sod()
            elif kw == "archetype":
                raw["archetype"] = self._word()
            elif kw == "metrics":
                raw["metrics"] = self._metrics()
            elif kw == "implemented_by":
                raw["implemented_by"] = self._implemented_by()
            else:
                self._fail(f"unknown section {kw!r}", tok)

    # sections ---------------------------------------------------------------------------------
    def _phrase_block(self) -> list[str]:
        """`{ "phrase", "phrase" }` — quoted discovery strings, comma-separated."""
        self._expect_punct("{")
        items: list[str] = []
        while not self._is_punct("}"):
            items.append(self._string())
            if self._is_punct(","):
                self._next()
        self._expect_punct("}")
        return items

    def _fields_block(self) -> list[dict[str, Any]]:
        """`{ name: Entity(Party) required; other: Money; }` — the typed contract slots."""
        self._expect_punct("{")
        fields: list[dict[str, Any]] = []
        while not self._is_punct("}"):
            name = self._word()
            self._expect_punct(":")
            field: dict[str, Any] = {"name": name, "type": self._field_type()}
            if self._is_word("required"):
                self._next()
                field["required"] = True
            self._expect_punct(";")
            fields.append(field)
        self._expect_punct("}")
        return fields

    def _field_type(self) -> dict[str, str]:
        head = self._word()
        if head in ("Entity", "List") and self._is_punct("("):
            self._next()
            of = self._word()
            self._expect_punct(")")
            return {"kind": "entity" if head == "Entity" else "list", "of": of}
        return {"kind": "scalar", "of": head}

    def _exposure(self) -> dict[str, Any]:
        self._expect_punct("{")
        exposure: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "ai":
                exposure["ai"] = self._bool()
            elif key == "roles":
                exposure["roles"] = self._id_list()
            else:
                self._fail(f"unknown exposure field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return exposure

    def _sod(self) -> dict[str, Any]:
        self._expect_punct("{")
        sod: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "preparer_not_approver":
                sod["preparer_not_approver"] = self._bool()
            else:
                self._fail(f"unknown sod field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return sod

    def _metrics(self) -> dict[str, Any]:
        self._expect_punct("{")
        metrics: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "sla":
                metrics["sla"] = self._string()
            else:
                self._fail(f"unknown metrics field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return metrics

    def _implemented_by(self) -> dict[str, str]:
        """`{ default: IssueInvoiceCycle; billing: OtherCycle }` — insertion order preserved."""
        self._expect_punct("{")
        impls: dict[str, str] = {}
        while not self._is_punct("}"):
            name = self._word()
            self._expect_punct(":")
            impls[name] = self._word()
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return impls

    def _bool(self) -> bool:
        tok = self._peek()
        word = self._word()
        if word == "true":
            return True
        if word == "false":
            return False
        self._fail(f"expected true or false but found {word!r}", tok)


def parse_capability_nil(text: str) -> Capability:
    """Parse `.capability.nil` source into a validated `Capability`. Malformed input — bad syntax OR
    an invalid shape the grammar allowed (unknown archetype, missing "default" implementation, bad
    semver) — refuses with `NilSyntaxError(message, line, col)`: a structured answer, not a crash."""
    tokens = _tokenize(text)
    reader = _CapabilityReader(tokens)
    raw = reader.capability()
    try:
        return Capability.model_validate(raw)
    except NilSyntaxError:
        raise
    except ValueError as exc:
        first = tokens[0]
        raise NilSyntaxError(f"invalid capability: {exc}", first.line, first.col) from exc


__all__ = ["parse_capability_nil", "NilSyntaxError"]
