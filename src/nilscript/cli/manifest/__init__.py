"""The requirements-manifest core (plan §4): the durable, shareable memory of a system's hidden
requirements, learned by collision so no one re-learns them.

This module owns the artifact's *shape* and its single load-bearing invariant — the
**structural/instance split** (plan §5, §6, §8):

- **Structural** requirements ("Sales Invoice needs `company`") are shared, public, PR-reviewed.
- **Instance** values (`company = "abc"`, API secrets) are private — env/config only.

`validate()` checks the shape; `shareable_violations()` is the sanitizer that makes leakage a
mechanical failure rather than a matter of discipline; `strip_instance()` derives a shareable copy.

The schema lives here as data (a Python structure), so the tool reads the standard's shape from one
place and carries no backend specifics — a manifest's *contents* are discovered, never embedded.
"""

from __future__ import annotations

import re
from typing import Any

MANIFEST_VERSION = "0.1"

# The requirement kinds an inference engine may record on a verb (plan §4.2/§4.3).
REQUIREMENT_KINDS = frozenset(
    {
        "required_scalar",  # a top-level required field the standard does not know about
        "required_on_line",  # a field required on each line/item of the native doc
        "required_nested",  # a field required inside a nested object
    }
)

# Substrings that mark an instance-values KEY as secret-bearing — forbidden in a shared manifest
# regardless of whether the value is a placeholder (plan §6 governance). Bias toward false positives:
# a benign field wrongly flagged costs a rename; a leaked credential in the public registry is the
# existential risk (plan §8). Any key ending in `key` (api_key, access_key, …) is also caught below.
_SECRET_KEY_HINTS = (
    "secret",
    "token",
    "password",
    "passwd",
    "private",
    "auth",
    "credential",
    "cred",
    "bearer",
    "jwt",
    "cert",
    "pem",
)

# A safe instance-values placeholder: a pure ${ENV_VAR} reference, no concrete value.
_ENV_PLACEHOLDER = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(_ENV_PLACEHOLDER.match(value))


def _looks_secret(key: str) -> bool:
    low = key.lower()
    if low == "key" or low.endswith("_key") or low.endswith("key"):  # api_key, access_key, apikey
        return True
    return any(hint in low for hint in _SECRET_KEY_HINTS)


def validate(manifest: dict[str, Any]) -> list[str]:
    """Structural validation of a manifest. Returns a list of human-readable errors ([] = valid).

    Hand-rolled (not jsonschema) so the `cli` extra stays dependency-light and the errors point at
    the exact verb/field that is wrong.
    """
    errors: list[str] = []

    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

    if not isinstance(manifest.get("manifest_version"), str):
        errors.append("missing or non-string `manifest_version`")
    if not isinstance(manifest.get("system"), str) or not manifest.get("system"):
        errors.append("missing or empty `system` (structural identity, e.g. \"erpnext\")")
    elif "://" in manifest["system"] or "." in manifest["system"].split("/")[0]:
        # A hostname/URL is an instance identity, not a structural one (plan §5 separation).
        errors.append(f"`system` looks like a hostname, not a structural id: {manifest['system']!r}")
    if not isinstance(manifest.get("nil_spec"), str):
        errors.append("missing or non-string `nil_spec`")

    verbs = manifest.get("verbs", {})
    if not isinstance(verbs, dict):
        errors.append("`verbs` must be an object keyed by verb name")
        verbs = {}
    for verb_name, entry in verbs.items():
        errors.extend(_validate_verb(verb_name, entry))

    for index, quirk in enumerate(manifest.get("transport_quirks", []) or []):
        loc = f"transport_quirks[{index}]"
        if not isinstance(quirk, dict):
            errors.append(f"{loc} must be an object")
            continue
        if not quirk.get("quirk"):
            errors.append(f"{loc} missing `quirk`")
        if not quirk.get("evidence"):
            errors.append(f"{loc} missing `evidence` (the native error that proves it)")

    return errors


def _validate_verb(verb_name: str, entry: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"verb {verb_name!r}: entry must be an object"]

    for index, req in enumerate(entry.get("hidden_requirements", []) or []):
        loc = f"verb {verb_name!r} hidden_requirements[{index}]"
        if not isinstance(req, dict) or not req.get("field"):
            errors.append(f"{loc} missing `field`")
            continue
        kind = req.get("kind")
        if kind not in REQUIREMENT_KINDS:
            errors.append(f"{loc} has unknown kind {kind!r} (expected one of {sorted(REQUIREMENT_KINDS)})")

    for index, prereq in enumerate(entry.get("prerequisites", []) or []):
        loc = f"verb {verb_name!r} prerequisites[{index}]"
        if not isinstance(prereq, dict) or not prereq.get("entity"):
            errors.append(f"{loc} missing `entity`")

    instance = entry.get("instance_values", {})
    if instance and not isinstance(instance, dict):
        errors.append(f"verb {verb_name!r}: `instance_values` must be an object")

    return errors


def shareable_violations(manifest: dict[str, Any]) -> list[str]:
    """Sanitizer (plan §6 governance, §8 leakage caveat): return reasons this manifest is NOT safe
    to publish to the community registry. [] means it carries structural requirements only.

    A manifest is unshareable if any verb's `instance_values` holds a concrete value (not a pure
    ${ENV} placeholder) or a secret-looking key — even a placeholdered secret key is rejected, so a
    leak can never ride in disguised as a reference.
    """
    violations: list[str] = []
    for verb_name, entry in (manifest.get("verbs", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        for key, value in (entry.get("instance_values", {}) or {}).items():
            where = f"{verb_name}.instance_values.{key}"
            if _looks_secret(key):
                violations.append(f"{where}: secret-bearing key forbidden in a shared manifest")
            elif not _is_placeholder(value):
                violations.append(f"{where}: concrete instance value {value!r} would leak — use a ${{ENV}} placeholder")
    return violations


def _req_key(req: dict[str, Any]) -> tuple[str, str]:
    return (req.get("field", ""), req.get("kind", ""))


def merge(base: dict[str, Any], *overrides: dict[str, Any]) -> dict[str, Any]:
    """Combine a community **structural** manifest with local **override** manifests (plan §3.4, §6).

    Requirements/prerequisites/quirks are unioned (dedup by identity); instance_values and per-verb
    scalars (native_target, line_container, …) are overlaid (later override wins). Pure: inputs are
    not mutated. This is how an integrator pulls `erpnext.manifest.json` and layers their own env
    bindings on top without re-discovering the structure.
    """
    import copy

    result = copy.deepcopy(base)
    result.setdefault("verbs", {})
    for override in overrides:
        for scalar in ("manifest_version", "system", "nil_spec"):
            if override.get(scalar):
                result[scalar] = override[scalar]
        for verb_name, entry in (override.get("verbs", {}) or {}).items():
            target = result["verbs"].setdefault(verb_name, {})
            _merge_verb(target, entry)
        if override.get("transport_quirks"):
            result["transport_quirks"] = _union_quirks(
                result.get("transport_quirks", []), override["transport_quirks"]
            )
    return result


def _merge_verb(target: dict[str, Any], entry: dict[str, Any]) -> None:
    existing = {_req_key(r) for r in target.get("hidden_requirements", [])}
    for req in entry.get("hidden_requirements", []):
        if _req_key(req) not in existing:
            target.setdefault("hidden_requirements", []).append(req)
            existing.add(_req_key(req))
    seen_entities = {p.get("entity") for p in target.get("prerequisites", [])}
    for prereq in entry.get("prerequisites", []):
        if prereq.get("entity") not in seen_entities:
            target.setdefault("prerequisites", []).append(prereq)
            seen_entities.add(prereq.get("entity"))
    if entry.get("instance_values"):
        target.setdefault("instance_values", {}).update(entry["instance_values"])
    for scalar in ("native_target", "line_container", "line_shape"):
        if entry.get(scalar):
            target[scalar] = entry[scalar]


def _union_quirks(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {q.get("quirk"): q for q in a}
    for quirk in b:
        by_name.setdefault(quirk.get("quirk"), quirk)
    return list(by_name.values())


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Structural diff between two manifest versions — drift detection when a system changes (§3.4).

    Reports verbs added/removed and, per shared verb, hidden requirements and prerequisites
    added/removed. `changed` is True iff anything differs (a quick gate for `manifest diff`).
    """
    old_verbs, new_verbs = old.get("verbs", {}) or {}, new.get("verbs", {}) or {}
    report: dict[str, Any] = {
        "verbs_added": sorted(set(new_verbs) - set(old_verbs)),
        "verbs_removed": sorted(set(old_verbs) - set(new_verbs)),
        "verbs_changed": {},
    }
    for verb in sorted(set(old_verbs) & set(new_verbs)):
        old_reqs = {_req_key(r) for r in old_verbs[verb].get("hidden_requirements", [])}
        new_reqs = {_req_key(r) for r in new_verbs[verb].get("hidden_requirements", [])}
        old_pre = {p.get("entity") for p in old_verbs[verb].get("prerequisites", [])}
        new_pre = {p.get("entity") for p in new_verbs[verb].get("prerequisites", [])}
        changes: dict[str, Any] = {}
        if new_reqs - old_reqs:
            changes["requirements_added"] = sorted(f"{f}:{k}" for f, k in new_reqs - old_reqs)
        if old_reqs - new_reqs:
            changes["requirements_removed"] = sorted(f"{f}:{k}" for f, k in old_reqs - new_reqs)
        if new_pre - old_pre:
            changes["prerequisites_added"] = sorted(str(e) for e in new_pre - old_pre)
        if old_pre - new_pre:
            changes["prerequisites_removed"] = sorted(str(e) for e in old_pre - new_pre)
        if changes:
            report["verbs_changed"][verb] = changes

    old_q = {q.get("quirk") for q in old.get("transport_quirks", [])}
    new_q = {q.get("quirk") for q in new.get("transport_quirks", [])}
    if new_q - old_q:
        report["quirks_added"] = sorted(str(q) for q in new_q - old_q)
    if old_q - new_q:
        report["quirks_removed"] = sorted(str(q) for q in old_q - new_q)

    report["changed"] = bool(
        report["verbs_added"]
        or report["verbs_removed"]
        or report["verbs_changed"]
        or report.get("quirks_added")
        or report.get("quirks_removed")
    )
    return report


def strip_instance(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a shareable copy of `manifest` with all `instance_values` removed, leaving only the
    structural requirements. Pure: the input is not mutated."""
    verbs: dict[str, Any] = {}
    for verb_name, entry in (manifest.get("verbs", {}) or {}).items():
        if isinstance(entry, dict):
            verbs[verb_name] = {k: v for k, v in entry.items() if k != "instance_values"}
        else:
            verbs[verb_name] = entry
    return {**manifest, "verbs": verbs}
