"""`_context_view` finds a caller's context keys wherever a stored context holds them.

Mantle stores a caller's keys at the top level, beside the facets the store owns. A row that no
write through mantle's `mint_context` has touched can also hold them under `caller`, alone or
beside some at the top level, and there a top-level read of a caller-supplied key answers nothing.
Measured against production:

    newest lead 08c6538d   ctx.source        -> None
                           ctx.caller.source -> 'website-contact'

    58 of 67 lead artifacts held their keys under `caller`; 9 held them at the top level.

`notify_inbound` prints a lead's source, company, role, interest, email_domain, lead_id and
marketing_opt_in from this view, and `_resolve_field` resolves the recipient of a templated email
through it. A key the view misses reads as "unknown", or as "No valid recipient resolved", with
no error.

Both shapes are live in one corpus, so the view merges rather than switching: the top level wins,
and `caller` supplies a key the top level does not hold.
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
        """A context with no `caller` reads exactly as stored."""
        ctx = {"source": "website-contact", "type": "lead"}
        assert server._context_view(ctx) == ctx

    def test_the_top_level_wins_over_the_mint(self):
        """The top level is the caller's current statement; a `caller` beside it is not."""
        ctx = {"source": "patched", "caller": {"source": "minted"}}
        assert server._context_view(ctx)["source"] == "patched"

    def test_a_json_string_context_is_parsed(self):
        """Mantle returns `context` as a string on the artifact read path."""
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

    def test_the_shape_mantle_stores_reads_as_stored(self):
        """The caller's keys at the top level beside the store's facets, and no `caller`."""
        ctx = {"minted_by": "mantle.mint_context", "provenance": "unknown", "source": "x"}
        assert server._context_view(ctx) == ctx

    def test_caller_supplies_only_what_the_top_level_lacks_and_never_a_store_key(self):
        ctx = {"source": "top", "caller": {"source": "old", "lead_id": "abc",
                                           "provenance": "human_validated"}}
        view = server._context_view(ctx)
        assert (view["source"], view["lead_id"]) == ("top", "abc")
        assert "provenance" not in view
