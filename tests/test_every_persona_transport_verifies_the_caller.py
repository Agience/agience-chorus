"""Every persona's MCP transport must verify the caller, not just the one that was caught.

⛔ SIX DID AND ONE DID NOT, AND THE DIFFERENCE WAS INVISIBLE FROM THE CODE. Measured 2026-09-15
against the running node: `POST /<persona>/mcp` with no bearer answered **401** for aria, astra,
sage, iris, seraph and lumen, and **200** for ophan — which issued a session id and then served
`tools/list` to a caller carrying no credential at all. ophan's own comment claimed the permissive
transport *"matches the other persona servers' pattern"*. It did not, and that sentence is why the
difference read as deliberate for as long as it did.

⚠ FIXING OPHAN DOES NOT FIX THIS. That was one persona; the next one added can repeat it, and the
only thing that noticed last time was someone probing seven endpoints by hand. A guard on one is not
a guard on the set — so this asserts the property across every persona discovered on disk, and the
cost of adding a persona that skips the wrapper is a red gate rather than an open front door.

⚠ DISCOVERED, NEVER LISTED. A hardcoded roster of seven names is a roster that a new persona is not
in, which makes this gate quietly narrower the day it matters most. The set comes from the tree.

WHAT THE WRAPPER IS. `prism.trust.ServerAuth.create_app(mcp)` — *"Verifies delegation JWTs on every
request"* — wraps the MCP ASGI app and is what turns a missing or invalid bearer into a 401 before
any tool is reached. A persona is free to wrap it further (ophan extracts operator claims on top,
aria and sage mount facets alongside), but `create_app` has to be in the chain.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "agience_chorus"

#: The verifying wrapper, and the bare app it must not be replaced by.
_VERIFIER = re.compile(r"_auth\.create_app\s*\(")
_BARE = re.compile(r"=\s*mcp\.streamable_http_app\s*\(\s*\)")


def _persona_servers() -> list[Path]:
    """Every `<persona>/server.py` under the package, found rather than named."""
    return sorted(
        p for p in SRC.glob("*/server.py")
        if "tests" not in p.parts and not p.parent.name.startswith("_")
    )


def test_personas_were_actually_found() -> None:
    """A discovery that quietly returns nothing makes every assertion below vacuously true.

    The exact shape this repository keeps producing: a gate whose subject moved, passing for ever
    while measuring an empty set.
    """
    found = _persona_servers()
    assert found, f"no persona server.py found under {SRC} — this gate is measuring nothing"
    assert len(found) >= 7, (
        "only %d personas found (%s); the roster has been seven since 2026-08. If one was "
        "legitimately removed, lower this floor deliberately." % (
            len(found), ", ".join(p.parent.name for p in found)))


@pytest.mark.parametrize("server", _persona_servers(), ids=lambda p: p.parent.name)
def test_the_transport_is_built_by_the_verifying_wrapper(server: Path) -> None:
    """`_auth.create_app` must appear in the chain that builds this persona's ASGI app."""
    source = server.read_text(encoding="utf-8-sig", errors="replace")
    assert _VERIFIER.search(source), (
        "%s does not build its transport with `_auth.create_app` — an unauthenticated MCP request "
        "would reach its tools. Every other persona wraps with it; see this module's docstring for "
        "what happened the last time one did not." % server.parent.name)


@pytest.mark.parametrize("server", _persona_servers(), ids=lambda p: p.parent.name)
def test_the_bare_unauthenticated_app_is_not_the_transport(server: Path) -> None:
    """The permissive form, named so it cannot come back by accident.

    ⚠ ASSIGNMENT, NOT MENTION. `mcp.streamable_http_app()` appearing in a comment or a docstring is
    prose about the fault and must stay allowed — a check that forbade the explanation would get
    the explanation deleted, which is how the reason for a rule is lost while the rule remains.
    """
    source = server.read_text(encoding="utf-8-sig", errors="replace")
    offenders = [
        line.strip() for line in source.splitlines()
        if _BARE.search(line) and not line.lstrip().startswith("#")
    ]
    assert not offenders, (
        "%s assigns the bare `mcp.streamable_http_app()` as its transport: that is the permissive "
        "form which answered 200 to a request with no token. Wrap with `_auth.create_app(mcp)`.\n  %s"
        % (server.parent.name, "\n  ".join(offenders)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
