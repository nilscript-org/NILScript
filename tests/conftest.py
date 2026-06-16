"""Make the PocketBase example shim importable so kernel executor tests can drive a real,
in-memory NIL adapter (FakeSystem) with no live backend. The example isn't an installed package."""

from __future__ import annotations

import sys
from pathlib import Path

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "examples" / "pocketbase-adapter" / "src"
if _EXAMPLE_SRC.is_dir() and str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))
