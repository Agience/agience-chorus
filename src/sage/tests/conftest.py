"""Sage's tests import its modules bare (`from web_extract import …`).

Under the repo's `--import-mode=importlib` (which fixes the cross-persona
`tests.test_*` name collisions) pytest does not insert the test file's parent
onto sys.path, so the persona dir is added explicitly here — the same thing the
server host does when it mounts sage.
"""
import os
import sys

_SAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SAGE_DIR not in sys.path:
    sys.path.insert(0, _SAGE_DIR)
