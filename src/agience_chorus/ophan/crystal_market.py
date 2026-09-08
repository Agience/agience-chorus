"""`crystal.market` — the market read as structure, so market signal can propagate.

Licence: chorus AGPL. Persona: ophan — market algorithms, knowledge, and processing over finance
and market data.

## Why a crystal and not tools on a persona

A crystal makes market signal a first-class citizen of the propagation model: a signal arrives at a
facet, a tekton condenses it, organons fire, and the result leaves by a facet. Nothing has to know a
tool's name, because coupling is measured rather than looked up
([[capability-is-an-artifact-matched-by-propagation]]).

## The four personas, and why the work is split across them

The boundary is drawn by where the world is, not by subject matter — and market data touches the
world at both ends:

    astra   ingestion real-world interface   → `op.fetch.get` (net.get). Bars and headlines arrive here.
    ophan   market algorithms + processing   → this crystal. Frames, co-registers, condenses. No world.
    aria    outgestion real-world interface  → the read leaves through aria's facet.
    lumen   reasoning, internal only         → may consume a read; may not fetch and may not present.

This crystal declares no `net.*` capability. Giving the market crystal its own fetcher — it is
*about* market data, after all — would put a second world-touching path in a persona whose job is
arithmetic, bypassing the one place SSRF and method-locking are enforced (`astra/fetch.py`). Bars
reach this crystal because astra put them in the store, and this crystal reads the store; that is
the whole coupling.

## What it declares

`facets` — the conduits. Two in, because a market read has two genuinely different inputs and merging
them into one conduit would hide that the second is optional: a price-only read is a real read, a
news-only one is not. One out, carrying the structural read.

`tektons` — one. Framing (`co_register`) is alignment, not condensation: it changes no type and makes
no decision, it puts observations on a shared clock. The condensation is the read — the moment an
ordered waveform becomes a typed, signable artifact, which is where the waveform-provenance boundary
sits ([[waveform-provenance-boundary]]). One crossing, one tekton.

`organons` — the instruments condensation invokes. `op.retrieve` (store.read) pulls the bars and news
artifacts back; `op.reason` (compute.local) is the instrument read. Both are also sage's: they are the
same two acts, and a third name for "read the store" would be a second vocabulary.
"""
from __future__ import annotations

from crystal.crystal_model import crystal_artifact, validate

MARKET = {
    "name": "crystal.market",

    "facets": [
        # The price conduit. `market-series` is a discovery hint and never a gate — the binding is
        # the waveform, and compatibility at a conduit is measured (does it couple), not typed.
        {"name": "bars", "direction": "in",
         "content_type": "application/vnd.agience.market-series+json"},
        # The attention conduit — headlines, and anything else that reports on the market rather than
        # being it. Separate from `bars` because it is optional and differently shaped: a read over
        # price alone is honest, a read over news alone has nothing to be a read of.
        {"name": "news", "direction": "in",
         "content_type": "application/vnd.agience.market-news+json"},
        # The read leaving — k_signal, top_share, the frame it was built from. `out` and not `both`:
        # a structural read is a statement about signal and never re-enters as signal, which is the
        # same discriminator that keeps `prism.instrument.Read` separate from `Instrument`.
        {"name": "read", "direction": "out"},
    ],

    "tektons": [
        # Condenses co-registered planes into a structural read. `domain` is the band it absorbs —
        # co-movement, not "market": what this tekton is tuned to is signals that move together, and
        # nothing about the condensation is specific to finance. A macro series, a sensor array and a
        # fleet of embers couple through the identical read.
        {"name": "op.market", "domain": "co-movement"},
    ],

    "organons": [
        # Read the bars and news artifacts back out of mantle. `store.read` only — this crystal never
        # writes; astra's ingest owns that path and owns it alone.
        {"name": "op.retrieve", "requires": ["store.read"]},
        # The instrument read (the host's screen seam). `compute.local` is the accurate capability here:
        # the read runs in-process on the host runtime, spawns nothing and reaches no network, which
        # is precisely what `compute.local` means. A subprocess-spawning organon, such as lumen's
        # `op.dev`, needs a different capability.
        {"name": "op.reason", "requires": ["compute.local"]},
    ],

    "created_by": "connect@agience.ai",
}

# Validated at import, exactly as `crystal.basics` and `crystal.comms` are. A crystal that fails its
# own contract must not be importable — a malformed crystal discovered at grounding time is a malformed
# crystal that already travelled.
assert validate(MARKET) == [], validate(MARKET)


def market_artifact() -> dict:
    """The market crystal as a store artifact — validated, sha-stamped, refusing tampering."""
    return crystal_artifact(MARKET)


__all__ = ["MARKET", "market_artifact"]
