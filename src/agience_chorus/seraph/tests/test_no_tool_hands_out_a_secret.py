"""No Seraph tool returns a decrypted secret.

A credential is decrypted only for the call it authorises, inside the operator that makes that call.
2026-10-29: `provide_aws_credentials` returned the plaintext AWS secret access key to any caller its
grants reached, and nothing in the platform called it. It is removed; this keeps it, and anything
like it, from returning.
"""
from __future__ import annotations

import json
from pathlib import Path

from agience_chorus import _persona

_server = _persona.load("server", __file__)
_MANIFEST = Path(__file__).resolve().parents[1] / ".well-known" / "mcp.json"


def test_no_registered_tool_provides_credentials():
    names = {t.name for t in _server.mcp._tool_manager.list_tools()}
    handing_out = sorted(n for n in names if n.startswith("provide_") and "credential" in n)
    assert not handing_out, f"a tool hands out credentials: {handing_out}"


def test_the_manifest_names_no_such_tool():
    tools = {t["name"] for t in json.loads(_MANIFEST.read_text(encoding="utf-8"))["tools"]}
    assert "provide_aws_credentials" not in tools
