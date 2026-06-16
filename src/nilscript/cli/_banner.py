"""The NILScript CLI banner — shown when `nilscript` is run with no subcommand.

Colors are emitted only to a TTY; piped/redirected output stays plain so it never corrupts logs or
captured stdout. The version is read from the installed package metadata, not hard-coded.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version


def _pkg_version() -> str:
    try:
        return version("nilscript")
    except PackageNotFoundError:  # running from source without an install
        return "0.0.0+src"


# ANSI palette — resolved to empty strings when stdout is not a terminal.
def _palette(color: bool) -> dict[str, str]:
    if not color:
        return {k: "" for k in ("RESET", "FRAME", "TEXT", "META", "SLOGAN", "BRACKET")}
    return {
        "RESET": "\033[0m",
        "FRAME": "\033[38;5;240m",  # slate gray
        "TEXT": "\033[1;37m",  # bold white
        "META": "\033[38;5;244m",  # zinc gray
        "SLOGAN": "\033[1;31m",  # security red
        "BRACKET": "\033[38;5;245m",
    }


def render(color: bool | None = None) -> str:
    """Return the banner string. `color` defaults to whether stdout is a TTY."""
    if color is None:
        color = sys.stdout.isatty()
    c = _palette(color)
    ver = _pkg_version()
    # The box interior is 72 visible columns; build the version line and pad to keep the border aligned.
    meta_inner = f"CLI Kernel Version {ver}".rjust(67) + " " * 5
    return f"""{c['FRAME']}┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   {c['TEXT']}Welcome to NILScript                                                 {c['FRAME']}│
│   {c['TEXT']}███╗  ██╗██╗██╗     ███████╗ ██████╗██████╗ ██╗██████╗ ████████╗     {c['FRAME']}│
│   {c['TEXT']}████╗ ██║██║██║     ██╔════╝██╔════╝██╔══██╗██║██╔══██╗╚══██╔══╝     {c['FRAME']}│
│   {c['TEXT']}██╔██╗██║██║██║     ███████╗██║     ██████╔╝██║██████╔╝   ██║        {c['FRAME']}│
│   {c['TEXT']}██║╚████║██║██║     ╚════██║██║     ██╔══██╗██║██╔═══╝    ██║        {c['FRAME']}│
│   {c['TEXT']}██║ ╚███║██║███████╗███████║╚██████╗██║  ██║██║██║        ██║        {c['FRAME']}│
│   {c['TEXT']}╚═╝  ╚══╝╚═╝╚══════╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═╝        ╚═╝        {c['FRAME']}│
│{c['META']}{meta_inner}{c['FRAME']}│
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘{c['RESET']}
 {c['BRACKET']}[ {c['SLOGAN']}TRUST NO AGENT {c['BRACKET']}] {c['META']}· The neutral standard for connecting systems to agents ·{c['RESET']}
"""
