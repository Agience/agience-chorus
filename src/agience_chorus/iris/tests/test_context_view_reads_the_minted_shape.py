"""A caller's context keys survive a create — one level down — and every reader must find them.

⛔ WHAT WAS WRONG, MEASURED AGAINST PRODUCTION 2026-09-11. Mantle mints a context onto every
create (`artifacts_router._mint_context`) and keeps the caller's own "verbatim under `caller`", by
its own stated contract. Iris read caller-supplied keys off the TOP level, so the moment minting
went live those reads answered nothing:

    newest lead 08c6538d   ctx.source        -> None                (what `notify_inbound` read)
                           ctx.caller.source -> 'website-contact'   (where it actually was)

    58 of 67 lead artifacts carry a minted context; 9 carry a flat one.

Nothing was lost and nothing errored — the operator notification just reported the source of 58
leads as "unknown", and company, role, interest, email_domain, lead_id and marketing_opt_in went
with it. `_resolve_field` reads the same way and resolves the RECIPIENT of a templated email, so
the same nesting answers "No valid recipient resolved" rather than sending to the wrong person.

BOTH SHAPES ARE LIVE IN ONE CORPUS — a PATCH does not mint, so patched artifacts stay flat — which
is why this merges rather than switching.
"""
from __future__ import annotations

import json

from agience_chorus.iris import server


class TestContextView:
    def test_the_minted_shape_finds_the_callers_key(self):
        ctx = {"addressing": {}, "minted_by": "mantle.mint_context",
               "caller": {"source": "website-contact", "lead_id": "abc"}}
        view = server._context_view(ctx)
        assert view["source"] == "website-contact"
        assert view["lead_id"] == "abc"

    def test_the_flat_shape_still_reads_exactly_as_before(self):
        """An artifact that was never minted, or was PATCHed, must be untouched by this."""
        ctx = {"source": "website-contact", "type": "lead"}
        assert server._context_view(ctx) == ctx

    def test_the_top_level_wins_over_the_mint(self):
        """A PATCH is a deliberate statement; the mint is a record of what the create carried."""
        ctx = {"source": "patched", "caller": {"source": "minted"}}
        assert server._context_view(ctx)["source"] == "patched"

    def test_a_json_string_context_is_parsed(self):
        """Mantle returns `context` as a STRING on the artifact read path, not as a dict."""
        raw = json.dumps({"caller": {"source": "website-contact"}})
        assert server._context_view(raw)["source"] == "website-contact"

    def test_the_store_keys_remain_reachable(self):
        """Merging must not hide what the store observed — provenance is read elsewhere."""
        view = server._context_view({"provenance": "unknown", "caller": {"source": "x"}})
        assert view["provenance"] == "unknown"
        assert view["source"] == "x"

    def test_nothing_is_invented_when_there_is_no_caller_block(self):
        """The negative case: no `caller`, no synthesis, and absent keys stay absent."""
        assert server._context_view({"addressing": {}}) == {"addressing": {}}
        assert server._context_view({}) == {}
        assert server._context_view(None) == {}
        assert server._context_view("not json") == {}

    def test_a_non_dict_caller_does_not_raise(self):
        """`caller` is caller-influenced; a string or list there must not explode a notification."""
        assert server._context_view({"caller": "oops", "source": "flat"})["source"] == "flat"
        assert server._context_view({"caller": []}) == {"caller": []}
