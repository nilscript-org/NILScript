"""Compile a BizSpec to a CompiledPlan.

Usage:
  nilscript compile --bizspec <path> --domain <path> --registry <path> --output <path>

Reads:
  - BizSpec (L2): business intent + steps
  - Domain (D0): capability imports + bindings
  - Registry: capability definitions

Emits:
  - CompiledPlan (L3): structured, pinned, with governance envelope
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from nilscript.bizspec import BizSpec
from nilscript.capability import Capability
from nilscript.compiler import compile_bizspec, CompileRefusal
from nilscript.domain import Domain


def _cmd_compile(args: argparse.Namespace) -> int:
    """Compile a BizSpec to a CompiledPlan."""
    try:
        # Load inputs
        bizspec_text = Path(args.bizspec).read_text(encoding="utf-8")
        bizspec_data = json.loads(bizspec_text)
        bizspec = BizSpec(**bizspec_data)

        domain_text = Path(args.domain).read_text(encoding="utf-8")
        domain_data = json.loads(domain_text)
        domain = Domain(**domain_data)

        registry_text = Path(args.registry).read_text(encoding="utf-8")
        registry_data = json.loads(registry_text)
        # registry_data is expected to be a list of capability dicts
        registry = [Capability(**cap) for cap in registry_data]

        # Compile
        compiled = compile_bizspec(bizspec, domain, registry)

        # Output
        output_dict = asdict(compiled)
        output_text = json.dumps(output_dict, indent=2, ensure_ascii=False, default=str)

        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
            print(f"✓ Compiled plan written to {args.output}", file=sys.stderr)
        else:
            print(output_text, file=sys.stdout)

        return 0

    except FileNotFoundError as e:
        print(f"✗ File not found: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"✗ JSON decode error: {e}", file=sys.stderr)
        return 1
    except CompileRefusal as e:
        print(f"✗ Compile refusal: {e.code} — {e.detail}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Compilation failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
