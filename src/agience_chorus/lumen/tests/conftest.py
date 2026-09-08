"""Lumen's tests need a chorus service identity, and they must say so.

`run_workflow` signs outbound JWTs through `origin.service_identity.sign_service_jwt`, which raises
if no identity is loaded (`RuntimeError: Service identity not initialized`). Without this fixture,
lumen's tests pass only when run alongside `src/tests/test_personas.py`, whose import of `personas`
calls `init_service_identity("chorus")` as a side effect — a dependency on another test file's import
order, not a real dependency.

The fixture has one home (`src/_chorus_identity.py`); importing it here registers it for this
persona explicitly.
"""
from __future__ import annotations

import os
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agience_chorus._chorus_identity import _chorus_test_identity  # noqa: F401,E402  (autouse, session-scoped)
