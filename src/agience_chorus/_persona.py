"""Load a persona-local module by its real, qualified name.

`load("reach_provider", __file__)` returns `agience_chorus.<persona>.reach_provider` for whichever
persona the calling file lives in.

## Why this is now four lines

It used to be sixty. `sys.modules` is process-global and keyed by name, and `reach_provider.py`,
`manifest.py` and `server.py` each exist in several personas — so a bare `import reach_provider`
meant whichever persona imported it first, and a test could silently receive a different persona's
module and fail with an `AttributeError` naming an attribute of the wrong one. This module avoided
that by loading the file by path and registering it under an invented `<persona>.<module>` key.

The personas are packages now, so `agience_chorus.sage.reach_provider` and
`agience_chorus.lumen.reach_provider` are already two different names. Python's own module cache
does what the invented keys were standing in for, and the hazard is gone at the root rather than
worked around. What remains is the convenience of not writing the persona's name at each call site.
"""

from __future__ import annotations

import importlib
from pathlib import Path

PACKAGE = "agience_chorus"


def persona_dir(anchor_file: str) -> Path:
    """The persona root for a file anywhere under `<src>/agience_chorus/<persona>/…`."""
    p = Path(anchor_file).resolve()
    for parent in p.parents:
        if parent.name == PACKAGE:
            raise RuntimeError(
                f"{p} is directly under {PACKAGE}/ — there is no persona directory to anchor to")
        if parent.parent.name == PACKAGE:
            return parent
    raise RuntimeError(f"{p} is not under a chorus `{PACKAGE}/<persona>/` tree")


def persona_name(anchor_file: str) -> str:
    """The persona a file belongs to — `"sage"` for anything under `agience_chorus/sage/`."""
    return persona_dir(anchor_file).name


def load(name: str, anchor_file: str):
    """Import `agience_chorus.<persona>.<name>` for the calling file's persona. Idempotent.

    Raises `ModuleNotFoundError` naming the persona and the module, as before — a caller asking for
    a module its persona does not own is a mistake worth reading, not an empty result.
    """
    persona = persona_name(anchor_file)
    try:
        return importlib.import_module(f"{PACKAGE}.{persona}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"{PACKAGE}.{persona}.{name}":
            raise ModuleNotFoundError(
                f"{persona} has no module {name!r} — check the persona owns it") from exc
        raise                                   # something the module itself imports is missing
