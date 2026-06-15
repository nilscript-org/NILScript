"""Enable `python -m nilscript.cli` (the console-script entry point is `nilscript`)."""

from nilscript.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
