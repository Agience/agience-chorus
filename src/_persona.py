"""Load a persona-local module under a unique name.

`sys.modules` is process-global and keyed by name, so a bare `import reach_provider` means whichever
persona imported it first — and `reach_provider.py`, `manifest.py`, and `server.py` each exist in
several personas. A test that reaches its own module by a bare name can silently receive a different
persona's module instead, with an `AttributeError` naming an attribute of the wrong persona's version.

`load("reach_provider", __file__)` loads the module from the calling test's own persona directory and
registers it as `<persona>.<module>`, so two personas' same-named modules are two different objects
and neither can be substituted for the other.

It does not put a bare `reach_provider` in `sys.modules` — the bare name is the hazard this avoids. If
a module needs a sibling, it should be loaded the same way.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def persona_dir(anchor_file: str) -> Path:
    """The persona root for a file anywhere under `<src>/<persona>/…`."""
    p = Path(anchor_file).resolve()
    for parent in p.parents:
        if parent.name == "src":
            raise RuntimeError(
                f"{p} is directly under src/ — there is no persona directory to anchor to")
        if parent.parent.name == "src":
            return parent
    raise RuntimeError(f"{p} is not under a chorus `src/<persona>/` tree")


def load(name: str, anchor_file: str):
    """Import `<persona>/<name>.py` as `<persona>.<name>`. Idempotent."""
    root = persona_dir(anchor_file)
    unique = f"{root.name}.{name}"
    if unique in sys.modules:
        return sys.modules[unique]

    path = root / f"{name}.py"
    if not path.is_file():
        raise ModuleNotFoundError(
            f"{root.name} has no module {name!r} at {path} — check the persona owns it")

    # the persona dir must be importable for the module's own bare sibling imports to resolve
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    spec = importlib.util.spec_from_file_location(unique, path)
    module = importlib.util.module_from_spec(spec)
    # registered before exec_module: dataclass/annotation resolution needs the name present, and a
    # circular sibling import would otherwise re-enter and build a second copy.
    sys.modules[unique] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(unique, None)
        raise
    return module
