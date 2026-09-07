"""aria's facets — the rendered views.

A facet is a persona's view of something. It has no business living in the runner: ember runs
things, it does not decide what they look like. This package holds the presentation code that
belongs to aria rather than to ember.

    dashboard_render.py   pure — its only import is dashboard_assets
    dashboard_assets.py   inlined brand assets

The browse view is not here: it reaches into six ember packages (`identity`, `store`, `runtime`,
`surface`, `mesh`, `genesis`), and moving it as-is would create `aria → ember`, the dependency
direction the persona split forbids. It stays a facet+tekton pair over data ember already
publishes, rather than a module that reaches into ember directly.

Ember does not import this package: ember must never import chorus. `ember.surface.stats` holds
an injection seam (`_DASHBOARD_RENDERER`) that a host wires — the same store-and-forward shape the
lumen chat chain uses, and for the same reason. Unwired, publishing the public status page
declines rather than rendering; it does not crash, and it does not overwrite a good page with an
empty one.
"""
from aria.facets.dashboard_render import render_dashboard  # noqa: F401

__all__ = ["render_dashboard"]
