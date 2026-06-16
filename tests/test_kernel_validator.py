"""The kernel's DSL validator must match the conformance corpus verdict contract.

For every program in `dsl/conformance/`, the validator must produce the manifest's `result`, emit
(at least) every listed diagnostic `code` for FAIL cases, and emit the listed non-blocking WARNING
codes for OK cases (e.g. V4_DEPRECATED_VERB). Mirrors AWS ValidateStateMachineDefinition: branch on
result + codes, never on wording.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nilscript.kernel import ValidationContext, validate

_CORPUS = Path(__file__).resolve().parents[1] / "src" / "nilscript" / "dsl" / "conformance"
_MANIFEST = json.loads((_CORPUS / "manifest.json").read_text())["cases"]
_CTX = ValidationContext.from_corpus(json.loads((_CORPUS / "context.json").read_text()))


@pytest.mark.parametrize("rel", sorted(_MANIFEST))
def test_corpus_case_matches_manifest(rel: str) -> None:
    expect = _MANIFEST[rel]
    program = json.loads((_CORPUS / rel).read_text())

    result = validate(program, _CTX)
    got_codes = {d.code for d in result.diagnostics}

    assert result.result == expect["result"], (rel, sorted(got_codes))

    # FAIL cases list the blocking codes; OK cases list non-blocking WARNING codes. Either way the
    # validator must emit at least every listed code (a superset is allowed).
    required = set(expect.get("codes", [])) | set(expect.get("diagnostics", []))
    assert required.issubset(got_codes), (rel, "missing", required - got_codes)
