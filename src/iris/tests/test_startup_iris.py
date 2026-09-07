"""Startup smoke test — verifies server_startup() completes without error."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# 2026-08-26: two dead path-insert lines stood here and are removed. MEASURED, not
# assumed — this test passes without either. `pytest.ini:34` (`pythonpath = src`) is what
# actually puts `src` on the path, and its own comment says why. The removed lines' comments
# had drifted three ways across the personas and only `seraph`'s described this tree.
# `lumen` KEEPS its two and must: it imports the bare-name sibling `reasoning`, so
# `src/lumen` has to be on the path. See `src/_persona.py`.



# 2026-08-26: an inline copy of this loader lived here. `src/_persona.py` is its one home
# and does strictly more — it pops the half-built module from `sys.modules` when
# `exec_module` raises, instead of leaving a broken one for the next importer, and it raises
# a ModuleNotFoundError naming the persona when the file is absent.
import _persona  # noqa: E402

_server = _persona.load("server", __file__)


@pytest.mark.asyncio
async def test_server_startup_calls_auth_startup():
    """server_startup() must delegate to _auth.startup() and not raise."""
    with patch.object(_server._auth, "startup", new_callable=AsyncMock) as mock_startup:
        await _server.server_startup()
    mock_startup.assert_called_once_with()
