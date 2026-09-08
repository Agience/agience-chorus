"""Guard: a tool that acts on a caller-supplied resource id must not use the
persona's service identity.

All Chorus personas share one ``chorus.private.pem``. A tool that takes a
``workspace_id`` / ``artifact_id`` from its arguments and then calls Mantle with
``_headers()`` (or ``_user_headers()``, which silently falls back to the same
platform JWT when no delegation is in context) makes Mantle apply *platform*
authority to a *caller-chosen* resource — a cross-tenant read/write primitive.

Such tools must call ``_require_user_headers()``, which fails closed.

This is an AST check, not a grep: it resolves which enclosing function each call
sits in, so a helper that legitimately uses the service identity elsewhere in the
same file does not trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Persona servers live under src/<persona>/server.py. Anchored here, not at the repo root:
# anchoring elsewhere makes the glob match zero persona files, and the guard passes vacuously on an
# empty scan.
SRC = Path(__file__).resolve().parents[1] / "src" / "agience_chorus"
# The chorus PACKAGE root — personas are `agience_chorus.<persona>` subpackages, not bare
# directories under `src/`.


# Argument names that carry a caller-chosen resource identity.
RESOURCE_ARGS = {
    "workspace_id",
    "artifact_id",
    "collection_id",
    "container_id",
    "source_artifact_id",
    "credential_artifact_id",
    "person_id",
}

# Header helpers that resolve to the persona's platform JWT — either always
# (`_headers`) or on fallback when no delegation is in context (`_user_headers`).
SERVICE_IDENTITY_HELPERS = {"_headers", "_user_headers"}

# Known-unfixed sites. This is a debt list, not an approval list — every entry would be a live
# cross-tenant exposure awaiting migration to _require_user_headers(). It exists so the check gates
# *new* regressions while a sweep proceeds. The list may only shrink; deleting the last entry is the
# definition of done. It is currently empty.
#
# Note on `_user_headers` entries: those are not safe. `user_headers()` falls back to the persona's
# platform JWT when no delegation is in context, and the middleware stores an empty token whenever
# verification or minting fails — so a `_user_headers` site escalates to service identity on exactly
# the requests that failed authentication.
BASELINE_UNFIXED: dict[tuple[str, str], str] = {}


# ── intentional, not debt ───────────────────────────────────────────────────────────────────────
# A debt entry means "a live cross-tenant exposure awaiting migration"; the four sites below are
# not awaiting anything, so they live in a separate table rather than the debt list.
#
# What they are. All four sit on the Stripe webhook path: an HTTP POST from Stripe, verified by HMAC
# against the signing secret, dispatched by `_handle_stripe_webhook_http` → `_dispatch_stripe_event`.
# There is no delegated caller anywhere in that path — Stripe holds no delegation JWT and no user is
# present — so `_require_user_headers()` cannot be used: it would fail closed on every real event,
# which means the subscription a customer just paid for is never activated. They therefore use
# `_platform_request`, ophan's explicit platform-identity call, kept as a separate function from
# `_request` so a static check can tell the two apart (see its docstring).
#
# Why that is safe here, stated as a property rather than a promise. The danger this file exists to
# catch is platform authority applied to a caller-chosen resource. On this path the `person_id` is
# not caller-chosen: it comes out of `event["data"]["object"]["metadata"]`, from a payload whose HMAC
# was verified against the signing secret before dispatch, and metadata that ophan itself wrote when
# it created the session. An attacker who could choose the `person_id` would have to forge a Stripe
# signature. The signature check is the authorization on this path — which is why
# `_resolve_stripe_webhook_secret` raises rather than degrading (`ophan/server.py`): if the signing
# secret is unresolvable, these four must never run at all, and the endpoint answers 503.
#
# This list is not an amnesty. It is load-bearing for the checks below: an entry here is exempted
# from `test_no_new_service_identity_on_caller_supplied_ids` exactly as a baseline entry is, so
# adding one is adding an exemption. It may only grow with a written justification of the same shape
# as the paragraph above — a stated property that makes caller-choice impossible, not an assertion
# that the code is fine. `test_intentional_sites_are_still_live` keeps every entry honest: if one
# stops using the service identity, it must leave this list too, so the exemption cannot outlive the
# thing it exempts.
INTENTIONAL_SERVICE_IDENTITY: dict[tuple[str, str], str] = {
    ("ophan", "_add_vu_to_core"): "['person_id'] + [via _platform_request → _headers] — Stripe WEBHOOK path, no delegated caller; person_id comes from HMAC-verified event metadata",
    ("ophan", "_sync_limits_to_core"): "['person_id'] + [via _platform_request → _headers] — Stripe WEBHOOK path, no delegated caller; person_id comes from HMAC-verified event metadata",
    ("ophan", "activate_subscription"): "['person_id'] + [via _sync_limits_to_core → _platform_request → _headers] — reached from _dispatch_stripe_event",
    ("ophan", "update_subscription"): "['person_id'] + [via _sync_limits_to_core → _platform_request → _headers] — reached from _dispatch_stripe_event",
}

#: Every site this check tolerates, for whichever reason. Two dicts rather than one flag: the
#: difference between "not fixed yet" and "correct by construction" is not expressible as a value in
#: one table, and the moment it is, the debt count stops meaning anything.
_EXEMPT = {**BASELINE_UNFIXED, **INTENTIONAL_SERVICE_IDENTITY}

def _persona_files() -> list[Path]:
    return sorted(p for p in SRC.glob("*/server.py") if p.parent.name != "_shared")


def _called_names(node: ast.AST) -> set[str]:
    """Every bare function name called anywhere inside ``node``."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            names.add(sub.func.id)
    return names


def _service_identity_reachers(tree: ast.AST) -> dict[str, str]:
    """Module-local functions that reach a service-identity helper, → the chain that gets there.

    A function that calls `_headers`/`_user_headers` only indirectly — through a module-local
    wrapper such as `_request(method, path, payload)` — would otherwise go undetected, since the
    wrapper's own parameters carry no resource-id names. This resolves reachability transitively
    rather than special-casing any one wrapper, so the next wrapper someone writes does not reopen
    the same hole. Cycles are handled by the worklist (a mutually-recursive pair would otherwise
    spin).
    """
    calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls[node.name] = _called_names(node)

    # Seed with the helpers themselves, then propagate "reaches" backwards until nothing changes.
    chain: dict[str, str] = {h: h for h in SERVICE_IDENTITY_HELPERS}
    changed = True
    while changed:
        changed = False
        for fn, called in calls.items():
            if fn in chain:
                continue
            for target in sorted(called):
                if target in chain:
                    chain[fn] = "%s → %s" % (fn, chain[target])
                    changed = True
                    break
    # Drop the seeds: a helper is not itself a violating call site.
    return {k: v for k, v in chain.items() if k not in SERVICE_IDENTITY_HELPERS}


def _violations(path: Path) -> list[tuple[str, str, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"), filename=str(path))
    module = path.parent.name
    out: list[tuple[str, str, int, str]] = []
    reachers = _service_identity_reachers(tree)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        args = node.args
        argnames = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        taken = argnames & RESOURCE_ARGS
        if not taken:
            continue

        called = _called_names(node)
        direct = called & SERVICE_IDENTITY_HELPERS
        if direct:
            out.append((module, node.name, node.lineno, f"{sorted(taken)} + {sorted(direct)}"))
            continue
        # INDIRECT: reaches a helper through one or more module-local hops. Reported with the chain,
        # because "grant_access uses the service identity" is actionable and "something somewhere in
        # this call tree does" is not.
        indirect = sorted(t for t in called if t in reachers)
        if indirect:
            out.append((module, node.name, node.lineno,
                        f"{sorted(taken)} + [via {reachers[indirect[0]]}]"))

    return out


def _all_violations() -> list[tuple[str, str, int, str]]:
    return [v for path in _persona_files() for v in _violations(path)]


def test_no_new_service_identity_on_caller_supplied_ids():
    """No site outside the exempt set (debt baseline + intentional) may use the service identity."""
    new = [v for v in _all_violations() if (v[0], v[1]) not in _EXEMPT]
    if new:
        lines = "\n".join(
            f"  {mod}/server.py:{line}  {fn}()  takes {detail}" for mod, fn, line, detail in new
        )
        pytest.fail(
            f"{len(new)} NEW tool(s) act on a caller-supplied resource id using the persona's "
            f"service identity — Mantle will apply platform authority to a caller-chosen "
            f"resource.\n"
            f"Use _require_user_headers(), which fails closed when no delegation is present.\n\n"
            f"{lines}"
        )


def test_baseline_only_shrinks():
    """A fixed site must be removed from the baseline, so the debt count is honest."""
    live = {(mod, fn) for mod, fn, _, _ in _all_violations()}
    fixed = set(BASELINE_UNFIXED) - live
    assert not fixed, (
        "These sites no longer use the service identity — delete them from "
        f"BASELINE_UNFIXED: {sorted(fixed)}"
    )


def test_intentional_sites_are_still_live():
    """An intentional entry must still be a real service-identity site.

    This guards against an exemption that outlives what it exempts. If `activate_subscription`
    is reached only from a delegated caller and moves to `_require_user_headers`, its entry here
    would go on excusing a name that no longer needs excusing — and the next function to take
    that name would inherit the exemption for free. Same rule as `test_baseline_only_shrinks`, applied
    to the list that is not debt: every exemption must be earning its place at the moment it is read.
    """
    live = {(mod, fn) for mod, fn, _, _ in _all_violations()}
    stale = set(INTENTIONAL_SERVICE_IDENTITY) - live
    assert not stale, (
        "These sites no longer use the service identity, so the intentional exemption is stale — "
        f"delete them from INTENTIONAL_SERVICE_IDENTITY: {sorted(stale)}"
    )


def test_intentional_sites_are_all_principal_less():
    """Every intentional exemption must be on ophan's Stripe-webhook path — nothing else qualifies.

    This guards against `INTENTIONAL_SERVICE_IDENTITY` becoming the place people put a site they do
    not want to fix. The justification in the block comment is a property of one path (no delegated
    caller exists; the id comes from an HMAC-verified payload), and it does not generalise. Pinning
    the roster means widening the exemption is a visible edit to this assertion rather than a new
    dict key.
    """
    assert set(INTENTIONAL_SERVICE_IDENTITY) == {
        ("ophan", "_add_vu_to_core"),
        ("ophan", "_sync_limits_to_core"),
        ("ophan", "activate_subscription"),
        ("ophan", "update_subscription"),
    }, (
        "the intentional-exemption roster changed. Only the principal-less Stripe-webhook path "
        "qualifies; anything else is debt and belongs in BASELINE_UNFIXED with a plan to remove it."
    )


def test_baseline_progress_is_visible(capsys):
    """Reports remaining debt so a change to `BASELINE_UNFIXED` is never silent, and pins the
    baseline at zero.

    The debt list is closed at zero: a new exposure must not be added to it. A new site that takes a
    resource id and uses the service identity is either fixed immediately, or — only on ophan's
    principal-less Stripe-webhook path, where the resource id is not actually caller-chosen — added
    to `INTENTIONAL_SERVICE_IDENTITY` with a stated property. The companion
    `test_no_new_service_identity_on_caller_supplied_ids` is what fails when a new site instead uses
    the service identity un-exempted; raising this ceiling to accommodate new code would be exactly
    the softening this file exists to prevent.
    """
    remaining = len(BASELINE_UNFIXED)
    with capsys.disabled():
        # Both numbers are printed. The intentional count is not debt, but it is still an exemption,
        # and an exemption that stops being reported stops being reviewed — which is how a "correct by
        # construction" note becomes a place to hide a site. Debt is what must go to zero; intentional
        # is what must stay justified (see `test_intentional_sites_are_all_principal_less`).
        print(f"\n[chorus] service-identity debt remaining: {remaining} site(s)"
              f"  |  intentional (principal-less webhook): "
              f"{len(INTENTIONAL_SERVICE_IDENTITY)} site(s)")
    assert remaining == 0, (
        "baseline grew — a new exposure was added to the debt list. Fix the site; do not raise this "
        "ceiling to accommodate new code. The debt list is closed at 0; an intentional "
        "platform-identity site goes in INTENTIONAL_SERVICE_IDENTITY with a stated property, never "
        "back into the debt list.")
