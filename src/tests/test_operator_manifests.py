"""Each persona owns its organons and declares the operators it offers in a sibling `manifest.py`,
and `load_personas` attaches that manifest to the persona's binding. The host registers per-persona;
there is no shared catalog. (Uses the chorus test-identity fixture from conftest to load the
personas.)"""
from __future__ import annotations


def _by_name():
    from agience_chorus import personas  # imported lazily so the session chorus-identity fixture materializes the key first
    return {b.name: b for b in personas.load_personas()}


def test_each_persona_owns_exactly_its_operators():
    b = _by_name()

    lumen_ids = {o["id"] for o in b["lumen"].operators}
    assert "op.reason" in lumen_ids
    assert len({i for i in lumen_ids if i.startswith("op.math.")}) == 13
    assert {i for i in lumen_ids if i.startswith("op.check.")}
    assert {i for i in lumen_ids if i.startswith("op.dev.")}
    assert "op.retrieve" not in lumen_ids, "op.retrieve is sage's — lumen reaches it, never owns it"

    sage_ids = {o["id"] for o in b["sage"].operators}
    assert "op.retrieve" in sage_ids
    assert {i for i in sage_ids if i.startswith("op.corpus.")}
    assert {i for i in sage_ids if i.startswith("op.docs.")}
    assert {i for i in sage_ids if i.startswith("op.describe.")}

    assert {o["id"] for o in b["astra"].operators} == {"op.fetch.get"}
    # seraph owns both halves of the distribution path — `op.install` consumes a payload,
    # `op.bundle.observe`/`op.bundle.condense` produce one. They are one persona so the producer's
    # contract and the consumer's check cannot drift apart in two places.
    assert {o["id"] for o in b["seraph"].operators} == {
        "op.install", "op.bundle.observe", "op.bundle.condense"}

    iris_ids = {o["id"] for o in b["iris"].operators}
    assert {i for i in iris_ids if i.startswith("op.comms.")}   # iris owns the comms plane organon


def test_operatorless_personas_have_empty_manifests():
    """A persona with no operators yields an empty manifest rather than crashing. ophan's energy
    surface (`get_energy`/`settle_energy`) is exposed as MCP tools, not as `op.*` operator
    artifacts, so its operator manifest is legitimately empty. aria owns `op.web.bff` (the tekton
    behind its `www` facet, `aria/web_bff.py` and `aria/manifest.py`) and `op.identity.verify`.

    The roster is asserted, not assumed: if aria's registrar is ever removed, or ophan gains an
    operator, the counts below move and force the decision instead of drifting."""
    b = _by_name()
    assert b["ophan"].operators == [], \
        "ophan gained an operator artifact — decide whether it belongs there, then update this roster"

    # `op.identity.verify` is an organon, not a generator: it carries a bearer token to origin over
    # the wire and reports what the authority said, or refuses, but has no path that returns a
    # credential. aria is the presentation persona, where generation is forbidden, so this operator
    # belongs to aria rather than to astra (which owns the other outbound organon, `op.fetch.get`):
    # it exists solely to serve aria's `login` facet's decision points, and splitting it out would
    # send every login hop across two personas for no gain. origin stays a peer here —
    # `test_chorus_does_not_import_origin` covers it, and `aria/identity.py` imports no origin
    # module at any scope.
    aria_ids = {o["id"] for o in b["aria"].operators}
    assert aria_ids == {"op.web.bff", "op.identity.verify"}, (
        f"aria's operator set changed: {sorted(aria_ids)}. It owns the www-facet bff tekton and the "
        f"identity organon serving the login facet; aria is the PRESENTATION persona and GENERATION "
        f"is forbidden here (no-models), so a new operator on aria wants a deliberate decision, not "
        f"a silent addition.")


def test_no_operator_is_owned_by_two_personas():
    b = _by_name()
    owners: dict[str, str] = {}
    for name, binding in b.items():
        for o in binding.operators:
            assert o["id"] not in owners, f"{o['id']} owned by both {owners.get(o['id'])} and {name}"
            owners[o["id"]] = name
