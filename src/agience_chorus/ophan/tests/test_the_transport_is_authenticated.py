"""Ophan's MCP transport refuses an unauthenticated caller, and the Stripe webhook still does not.

⛔ THIS BEHAVIOUR WAS THE OTHER WAY ROUND, AND NOTHING FAILED. Measured 2026-09-15 against the
running node: `POST /ophan/mcp` with no bearer, and with an invalid one, was answered **200** with a
session id, and `tools/list` then succeeded — while aria, astra, sage, iris, seraph and lumen all
answered 401. The code carried a comment claiming the permissive transport *"matches the other
persona servers' pattern"*; it did not, and a comment asserting a parity that does not exist is how
the difference stopped being questioned.

The fix was one line — `_auth.create_app(mcp)`, the wrapper the other six use. The reason it was
safe is that the permissive transport's stated justification (*"allows MCP protocol calls (e.g.
type discovery at startup) to succeed without a token"*) was vestigial:

  · discovery is answered by `.well-known/mcp.json` at the host (`iris/comms/mcp_tekton.py`),
  · type registration is a PUSH to crystal's `POST /register`,
  · op dispatch arrives via `crystal.main:run_operation`, which calls `_require_bearer` and 401s
    without a token before forwarding the caller's.

⚠ NOTHING ASSERTED IT, WHICH IS WHY IT IS ASSERTED HERE. Reverting that one line restores the open
transport and every other test in this repository still passes. The economic persona's front door is
not a thing to leave resting on a line nobody checks.

⛔ AND THE WEBHOOK MUST STAY OPEN. `/webhooks/stripe` authenticates by signature, which is the only
credential an inbound webhook carries — putting it behind the bearer would silently stop every
Stripe delivery. It is checked here in the same file as the thing that would break it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agience_chorus import _persona

_server = _persona.load("server", __file__)
_SOURCE = (Path(__file__).resolve().parent.parent / "server.py").read_text(
    encoding="utf-8-sig", errors="replace")


class TestTheMcpTransportVerifiesTheCaller:
    def test_the_app_is_built_by_the_shared_verifying_wrapper(self):
        """`_auth.create_app` is what the other six personas use, and what emits the 401.

        Asserted on the SOURCE rather than by inspecting the returned ASGI callable: the wrapper
        returns a plain function, so there is nothing on the object to identify it by, and a
        structural check would pass against any function at all.
        """
        assert "_auth.create_app(mcp)" in _SOURCE, (
            "ophan no longer builds its transport with `_auth.create_app` — an unauthenticated MCP "
            "request reaches the tools again. See this module's docstring.")

    def test_it_does_not_fall_back_to_the_bare_unauthenticated_app(self):
        """The exact line that was there before, and must not return."""
        assert "inner_app = mcp.streamable_http_app()" not in _SOURCE, (
            "the bare `mcp.streamable_http_app()` is back as the transport's inner app; that is the "
            "permissive form that answered 200 to a request with no token at all.")

    def test_the_operator_claims_layer_survives_alongside_it(self):
        """Two layers, not one replacing the other.

        `_auth.create_app` says WHO is calling; `_current_operator_claims()` says what they may
        license. Five tools gate on the second, and dropping it while adding the first would let a
        merely-authenticated caller reach the licensing operations.
        """
        assert "_CURRENT_OPERATOR_CLAIMS.set(claims)" in _SOURCE
        assert _SOURCE.count("_current_operator_claims()") >= 5


class TestTheStripeWebhookStaysReachable:
    def test_the_route_is_matched_by_suffix_not_by_equality(self):
        """⛔ THE EQUALITY NEVER HELD, BECAUSE THIS APP IS MOUNTED AT `/ophan`.

        `path == "/webhooks/stripe"` was never true for a request the host routed, so every webhook
        fell through to the MCP app. While the transport was permissive that produced a 404/406 —
        a wrong answer shaped like a malformed webhook rather than an unrouted one — so the fault
        survived unnoticed until the transport was closed and it became a 401.
        """
        assert 'path == "/webhooks/stripe"' not in _SOURCE, (
            "the webhook is matched by equality again; mounted at /ophan that comparison never "
            "matches and every Stripe delivery falls through to the MCP app.")
        assert 'endswith("/webhooks/stripe")' in _SOURCE

    def test_the_webhook_is_checked_before_the_authenticated_app(self):
        """Order is the whole protection: behind the bearer, Stripe could never deliver."""
        webhook_at = _SOURCE.find("_handle_stripe_webhook_http(scope, receive, send)")
        mcp_at = _SOURCE.find("await mcp_app(scope, receive, send)")
        assert webhook_at != -1 and mcp_at != -1, "the dispatch shape has changed; re-read it"
        assert webhook_at < mcp_at, (
            "the Stripe branch no longer short-circuits ahead of the MCP app — a webhook would now "
            "be asked for a bearer token it has no way to carry.")

    def test_a_missing_signature_is_a_400_and_never_a_401(self):
        """The handler's own answer, and the one that proves it was reached at all.

        401 here means the request never got to the handler: it is what the MCP app says, not what
        this webhook says.
        """
        assert '"Missing Stripe-Signature header"' in _SOURCE
        assert '"status": 400' in _SOURCE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
