"""aria's facets — the rendered views.

A facet is a persona's view of something. It has no business living in the runner: ember runs
things, it does not decide what they look like. This package holds the presentation code that
belongs to aria rather than to ember.

    browse.py             the ontology browser — pages the corpus, renders an artifact and its edges
    dashboard_render.py   pure — its only import is dashboard_assets
    dashboard_assets.py   inlined brand assets

`browse.py` is here now, and the condition this note used to record is how it got here. It reached
into six ember packages, so moving it AS-IS would have created `aria → ember` — the direction the
split forbids. It was not moved as-is: every one of those reaches is now a HOST SEAM
(`genesis`, `improve`, `stats`, `pool`, resolved through `_host_seams`), and the two bundle groups
it loads come from `prism.runner`, which needs no host at all. The dependency does not exist, so
the objection does not either.

Ember does not import this package: ember must never import chorus. `ember.surface.stats` holds
an injection seam (`_DASHBOARD_RENDERER`) that a host wires — the same store-and-forward shape the
lumen chat chain uses, and for the same reason. Unwired, publishing the public status page
declines rather than rendering; it does not crash, and it does not overwrite a good page with an
empty one.
"""
from aria.facets.dashboard_render import render_dashboard  # noqa: F401

__all__ = ["render_dashboard"]

# `browse` is NOT re-exported. It resolves seams at call time, so importing this package would
# otherwise drag a host requirement into anything that only wanted the renderer.
