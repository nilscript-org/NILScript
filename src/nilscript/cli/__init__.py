"""nilscript CLI — general tooling to build and verify NIL adapters.

Reads the bundled standard only; contains zero specifics of any backend. The same tools let
any developer, anywhere, build an adapter for their own system from the standard alone:

    pip install nilscript[cli]
    nilscript verbs                 # the verb catalog (deprecated verbs flagged)
    nilscript profile <verb>        # a verb's arg-schema
    nilscript export-openapi        # the five-endpoint API surface as OpenAPI 3.1
"""

from __future__ import annotations

import argparse
import json
import sys

from nilscript.cli._openapi import build_openapi
from nilscript.cli._spec import SPEC_VERSION, all_verbs, load_profile


def _verb_markers(verb) -> str:  # type: ignore[no-untyped-def]
    parts = []
    if verb.deprecated:
        ref = f" — {verb.gap_ref}" if verb.gap_ref else ""
        parts.append(f"[DEPRECATED{ref} — not scaffolded]")
    if verb.tier_floor:
        parts.append(f"[floor {verb.tier_floor}]")
    return ("  " + "  ".join(parts)) if parts else ""


def _cmd_verbs(args: argparse.Namespace) -> int:
    verbs = all_verbs()
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "verb": v.name,
                        "deprecated": v.deprecated,
                        "gap_ref": v.gap_ref,
                        "tier_floor": v.tier_floor,
                        "required": list(v.required),
                    }
                    for v in verbs
                ],
                indent=2,
            )
        )
        return 0
    width = max((len(v.name) for v in verbs), default=0)
    deprecated = sum(1 for v in verbs if v.deprecated)
    print(
        f"{len(verbs)} verbs in the NIL standard (v{SPEC_VERSION}) — "
        f"{len(verbs) - deprecated} active, {deprecated} deprecated (excluded from scaffolding):\n"
    )
    for v in verbs:
        required = ", ".join(v.required) if v.required else "—"
        print(f"  {v.name:<{width}}  required: {required}{_verb_markers(v)}")
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    profile = load_profile(args.verb)
    if profile is None:
        print(f"unknown verb: {args.verb!r}", file=sys.stderr)
        print("run `nilscript verbs` to list the catalog.", file=sys.stderr)
        return 2
    print(json.dumps(profile, indent=2, ensure_ascii=False))
    return 0


def _cmd_export_openapi(args: argparse.Namespace) -> int:
    doc = build_openapi()
    if args.format == "yaml":
        try:
            import yaml
        except ModuleNotFoundError:
            print(
                "YAML output needs PyYAML (pip install nilscript[cli]); emitting JSON instead.",
                file=sys.stderr,
            )
            text = json.dumps(doc, indent=2)
        else:
            text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    else:
        text = json.dumps(doc, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nilscript",
        description="Tooling to build and verify NIL adapters from the standard.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_verbs = sub.add_parser("verbs", help="list the verb catalog from the standard")
    p_verbs.add_argument("--json", action="store_true", help="machine-readable output")
    p_verbs.set_defaults(func=_cmd_verbs)

    p_profile = sub.add_parser("profile", help="print a verb's arg-schema profile")
    p_profile.add_argument("verb", help="e.g. commerce.create_product")
    p_profile.set_defaults(func=_cmd_profile)

    p_openapi = sub.add_parser(
        "export-openapi", help="emit an OpenAPI 3.1 document for the five NIL endpoints"
    )
    p_openapi.add_argument("--format", choices=["json", "yaml"], default="json")
    p_openapi.add_argument("-o", "--output", help="write to a file instead of stdout")
    p_openapi.set_defaults(func=_cmd_export_openapi)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
