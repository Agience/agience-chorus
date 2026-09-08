"""Ophan must not carry an LLM metering surface, a bare outbound write, or an env-held secret.

Three standing rules meet in `ophan/server.py`, and this file pins their closure:

  1. No models, including BYOK. `check_llm_allowance` and `record_llm_usage` must raise rather than
     meter a forbidden capability, and must not appear in `tools/list`. Metering a forbidden capability
     keeps its path alive economically — a billing surface argues the thing is expected to exist.
  2. External operators are GET-only, the same structural boundary astra enforces in `fetch.py` (method
     hard-locked to GET, SSRF re-checked per redirect hop). The vendor SDK's write-call spelling
     (`Session.create`) must not appear in the source at all, and the tools that would have made those
     calls must refuse.
  3. Secrets do not live in a persona's environment. No `os.getenv` read or module attribute may name
     `STRIPE_SECRET_KEY` or `STRIPE_WEBHOOK_SECRET`, and the webhook-secret resolver must raise rather
     than return None or a default — a missing payments credential must not read as "billing is not
     configured".

Also pinned: `get_billing_summary` is absent. On the persona's platform identity it would be a
cross-tenant billing oracle over `/internal/gate/usage/{person_id}`; restoring `_platform_request`
restores the oracle, so the absence of the attribute is what this file guards.

The module is loaded under a unique name (see `_load_persona_server`), matching the other ophan tests:
every persona ships a `server.py`, and a bare `import server` races across the full run so a later
persona gets the wrong module. The filename here is likewise unique across chorus — duplicate test
basenames substitute silently under pytest and the file would be dropped without an error.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_HERE = Path(__file__).resolve().parent
_OPHAN_DIR = _HERE.parent
_SERVER_PY = _OPHAN_DIR / "server.py"


# 2026-08-26: an inline copy of this loader lived here. `src/_persona.py` is its one home
# and does strictly more — it pops the half-built module from `sys.modules` when
# `exec_module` raises, instead of leaving a broken one for the next importer, and it raises
# a ModuleNotFoundError naming the persona when the file is absent.
from agience_chorus import _persona  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.

_server = _persona.load("server", __file__)
_SOURCE = _SERVER_PY.read_text(encoding="utf-8-sig", errors="replace")


def _registered_tool_names() -> set[str]:
    """The names ophan actually advertises in `tools/list`."""
    return {t.name for t in _server.mcp._tool_manager.list_tools()}


def _live_code() -> str:
    """The module with every COMMENT and STRING token removed — i.e. executable code only.

    A plain substring scan is useless in this file: the removals it pins are documented at length, so
    `Session.create` and `STRIPE_SECRET_KEY` both appear dozens of times inside the tombstone comments
    and docstrings that explain why they are gone. Stripping only `#` tails is not enough either,
    because the module docstring is a STRING, not a comment. Tokenising is the honest cut: a live
    attribute access such as `stripe.checkout.Session.create` survives it, and every mention in prose
    does not.
    """
    import io
    import tokenize

    lines = _SOURCE.splitlines()
    dropped = {tokenize.COMMENT, tokenize.STRING}
    dropped |= {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                if hasattr(tokenize, n)}
    # Blank out each dropped token in place rather than re-joining tokens: a `" ".join` would split
    # `stripe.checkout.Session.create` into separate tokens and the very spelling being searched for
    # would stop matching — a check that cannot fail.
    for tok in tokenize.generate_tokens(io.StringIO(_SOURCE).readline):
        if tok.type not in dropped:
            continue
        (r0, c0), (r1, c1) = tok.start, tok.end
        for row in range(r0 - 1, min(r1, len(lines))):
            line = lines[row]
            lo = c0 if row == r0 - 1 else 0
            hi = c1 if row == r1 - 1 else len(line)
            lines[row] = line[:lo] + " " * (hi - lo) + line[hi:]
    return "\n".join(lines)


def _getenv_keys() -> set[str]:
    """Every literal key passed to `os.getenv` in the module — an AST read, not a grep, so a mention
    inside a comment or docstring (this module has many) is not mistaken for a live read."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(_SOURCE, filename=str(_SERVER_PY))):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_getenv = (
            (isinstance(fn, ast.Attribute) and fn.attr == "getenv")
            or (isinstance(fn, ast.Name) and fn.id == "getenv")
        )
        if is_getenv and node.args and isinstance(node.args[0], ast.Constant):
            keys.add(str(node.args[0].value))
    return keys


# ---------------------------------------------------------------------------
# 1. No LLM metering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_metering_tools_raise():
    """Both LLM-metering tools raise rather than answer, so neither's call path is live."""
    with pytest.raises(NotImplementedError, match="no-models"):
        await _server.check_llm_allowance(user_id="u", tier="pro", estimated_tokens=1000)
    with pytest.raises(NotImplementedError, match="no-models"):
        await _server.record_llm_usage(
            user_id="u", provider="anthropic", model="m", input_tokens=10, output_tokens=10,
        )


def test_llm_metering_tools_are_not_advertised():
    """Neither LLM-metering tool appears in `tools/list`. A raising tool that is still advertised still
    tells a client that token metering is part of this surface."""
    advertised = _registered_tool_names()
    assert "check_llm_allowance" not in advertised
    assert "record_llm_usage" not in advertised


def test_no_token_rate_or_tier_table_remains():
    """None of the token-rate/tier-table attributes exist. The tools are the argument against LLM
    metering; the tables are the same argument in data form, so a surviving rate table or budget would
    let the tools be rebuilt from what is left."""
    for gone in ("_TIER_LIMITS", "_get_vu_rate", "_usage_counters",
                 "_get_user_counter", "_maybe_reset_counters"):
        assert not hasattr(_server, gone), f"{gone} came back — token metering apparatus"


# ---------------------------------------------------------------------------
# 2. No bare outbound write
# ---------------------------------------------------------------------------

def test_no_vendor_sdk_write_calls_in_source():
    """The vendor SDK's write-call spelling does not occur anywhere in the live source. Text-scanned
    rather than AST-resolved on purpose: the point is that the spelling must not occur at all, including
    in a helper or a lazily-imported alias."""
    live = _live_code()
    for spelling in ("Session.create", "api_key"):
        assert spelling not in live, (
            f"{spelling!r} is live in ophan/server.py — an outbound write or a write-capable client "
            f"configured inside a persona. It belongs in the op.pay.session organon behind "
            f"net.request + the discharge gate (_scratch/OPHAN-STRIPE-TEKTON.md)."
        )


@pytest.mark.asyncio
async def test_session_creating_tools_refuse():
    """The three session-creating tools refuse, and stay registered while refusing, so a caller gets the
    reason rather than "unknown tool"."""
    advertised = _registered_tool_names()
    for name in ("create_checkout_session", "create_portal_session", "create_vu_topup"):
        assert name in advertised, f"{name} must remain registered so its refusal is addressed"

    with pytest.raises(_server.OphanToolError, match="outbound WRITE"):
        await _server.create_checkout_session(plan="pro", person_id="p")
    with pytest.raises(_server.OphanToolError, match="outbound WRITE"):
        await _server.create_portal_session(stripe_customer_id="cus_x")
    with pytest.raises(_server.OphanToolError, match="outbound WRITE"):
        await _server.create_vu_topup(person_id="p")


# ---------------------------------------------------------------------------
# 3. No secret from the environment
# ---------------------------------------------------------------------------

def test_no_stripe_secret_is_read_from_the_environment():
    """Neither Stripe secret is read from the environment or held as a module attribute. Asserted both
    ways because rehoming the read into a function would defeat an env-read check alone."""
    keys = _getenv_keys()
    assert "STRIPE_SECRET_KEY" not in keys
    assert "STRIPE_WEBHOOK_SECRET" not in keys
    assert not hasattr(_server, "STRIPE_SECRET_KEY")
    assert not hasattr(_server, "STRIPE_WEBHOOK_SECRET")
    # No gate silently treats an absent secret as "not configured" either.
    assert not hasattr(_server, "_stripe_enabled")
    assert not hasattr(_server, "_get_stripe")


@pytest.mark.asyncio
async def test_webhook_secret_resolver_raises_and_never_returns_none():
    """The webhook-secret resolver raises on every failure and never returns None or a default, so an
    unconfigured verifier cannot be mistaken for a malformed request."""
    with patch.object(_server, "_obtain_system_delegation", new_callable=AsyncMock) as deleg:
        deleg.return_value = ""          # Origin declined to issue a delegation
        with pytest.raises(_server.OphanToolError):
            await _server._resolve_stripe_webhook_secret()


# ---------------------------------------------------------------------------
# 4. The cross-tenant billing read is gone
# ---------------------------------------------------------------------------

def test_get_billing_summary_is_removed():
    """`get_billing_summary` is not a tool, not an attribute, and not advertised. Restoring
    `_platform_request` on the persona's platform identity would let it read any person's plan, limits,
    usage, and Stripe customer id — a cross-tenant billing read this file guards against."""
    assert not hasattr(_server, "get_billing_summary")
    assert not hasattr(_server, "_limits_to_plan")   # its only caller went with it
    assert "get_billing_summary" not in _registered_tool_names()


def test_internal_gate_usage_read_has_exactly_one_principal_less_site():
    """`/internal/gate/usage/` is read from exactly one function, `_add_vu_to_core`, which is reachable
    only from the signature-verified webhook, reads a person's current limits solely to add to them, and
    returns nothing to any caller. A second owning function would mean the read had been re-exposed
    somewhere quieter than a registered tool.

    Resolved by AST ownership rather than by counting occurrences: the route is named several times in
    the module's prose, and `_live_code()` cannot be used here because the route is a string literal in
    the one place it legitimately appears."""
    tree = ast.parse(_SOURCE, filename=str(_SERVER_PY))
    owners = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "/internal/gate/usage/" in ast.get_source_segment(_SOURCE, n)
    ]
    assert owners == ["_add_vu_to_core"], (
        f"the gate usage read moved or gained a caller: {owners}. It must stay on the "
        f"principal-less webhook path and must never answer an MCP caller."
    )
