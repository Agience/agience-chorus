"""Startup smoke test — verifies server_startup() completes without error."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Resolve paths absolutely so they work regardless of how pytest sets __file__.
_HERE = Path(__file__).resolve().parent  # .../servers/<name>/tests/
sys.path.insert(0, str(_HERE.parent.parent.parent))  # .../src (for `from core import ...`)
sys.path.insert(0, str(_HERE.parent))  # .../servers/<name>/



# Do not replace this with `_persona.load("server", __file__)`. It was tried on 2026-08-26
# and broke `test_no_inprocess_sage_load.py::test_the_grounding_budget_is_lumens_own_...`.
#
# `_persona.load` is IDEMPOTENT — it returns the module already in `sys.modules` under
# `<persona>.<name>`. This file loads at IMPORT time, so converting it would put `lumen.server` in
# the cache before that test runs; the test sets `LUMEN_GROUNDING_CHARS` with monkeypatch and then
# calls `_persona.load("server", __file__)` expecting a module that reads the env at import. It
# would get the cached one, loaded before the env was set, and assert 1234 against the default.
#
# The unique name here (`lumen_server_under_test`) keeps the two loads in separate cache slots,
# which is what makes both tests correct. The other eight persona startup tests WERE converted —
# none of them shares a persona with an env-dependent second load.
def _load_persona_server():
    """Load this persona's server.py under a unique module name.

    Every persona ships a `server.py`; a bare `import server` races across the test run —
    first import wins sys.modules and later personas get the wrong server. The host itself
    loads personas via importlib under unique names (src/server.py); tests mirror that."""
    import importlib.util as _ilu
    import sys as _sys
    from pathlib import Path as _P
    _dir = _P(__file__).resolve().parent.parent
    _name = "%s_server_under_test" % _dir.name
    if _name in _sys.modules:
        return _sys.modules[_name]
    _spec = _ilu.spec_from_file_location(_name, _dir / "server.py")
    _mod = _ilu.module_from_spec(_spec)
    _sys.modules[_name] = _mod
    _spec.loader.exec_module(_mod)
    return _mod

_server = _load_persona_server()  # unique-name load; see helper


@pytest.mark.asyncio
async def test_server_startup_calls_auth_startup():
    """server_startup() must delegate to _auth.startup() and not raise."""
    with patch.object(_server._auth, "startup", new_callable=AsyncMock) as mock_startup:
        await _server.server_startup()
    mock_startup.assert_called_once_with()
