"""op.install (seraph): an install bundle is a signed crystal (or set of crystals). Pins the bundle
sha gate, member-by-member crystal verification and sha-pin, grounding through the store, and the
per-organon activation report on the prism — a crystal grounds regardless of capability gaps; each
organon is lit if its capabilities are present, dormant (with the gap named) if not. There is no
`install.kind` and no package-manager shell-out; environment provisioning is the prism's concern."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from crystal.crystal_model import crystal_artifact

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import install  # noqa: E402


class _Capture:
    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


def _crystal(name="crystal.demo", requires=("compute.local", "store.read")):
    return {
        "name": name,
        "facets": [{"name": "chat", "direction": "both"}],
        "tektons": [{"name": "sage", "domain": "knowledge"}],
        "organons": [{"name": "op.respond", "requires": list(requires)}],
        "created_by": "person-1",
    }


def _bundle(crystal_art, *, content=""):
    """A minimal install bundle: just the signed crystal(s). No install.kind, no capability restatement."""
    pin = json.loads(crystal_art["content"])["sha256"]
    manifest = {
        "sha256": install.sha256_of(content),
        "crystals": [{"name": crystal_art["name"], "sha256": pin}],
        "created_by": "person-1",
    }
    return {"id": "bundle.demo", "name": "bundle.demo",
            "content_type": install.BUNDLE_CONTENT_TYPE,
            "context": json.dumps(manifest), "content": content}


def _fetcher(*arts):
    by_name = {a["name"]: a for a in arts}
    return lambda name: by_name.get(name)


def test_register_install_operator():
    store = _Capture()
    assert install.register_install_operators(store) == 1
    doc = store.docs["op.install"]
    assert doc["content_type"] == "application/vnd.agience.operator+json"
    assert "prism" in doc["context"] and "activation" in doc["context"]   # names the prism + activation report


def test_tampered_bundle_refused_loudly():
    art = crystal_artifact(_crystal())
    b = _bundle(art, content="payload-bytes")
    b["content"] = "payload-bytes-tampered"
    with pytest.raises(ValueError, match="integrity failure"):
        install.install_bundle(b, ["compute.local", "store.read"], _fetcher(art))


def test_grounds_and_reports_activation_when_the_prism_affords_it():
    art = crystal_artifact(_crystal())
    store = _Capture()
    out = install.install_bundle(_bundle(art), ["compute.local", "store.read"], _fetcher(art), store=store)
    assert out["status"] == "grounded"
    assert store.docs["crystal.demo"]["content"] == art["content"]   # structure recorded verbatim
    c = out["crystals"][0]
    assert c["lit"] == ["op.respond"] and c["dormant"] == []          # fully lit here


def test_returns_the_validated_plan_without_a_store():
    art = crystal_artifact(_crystal())
    out = install.install_bundle(_bundle(art), ["compute.local", "store.read"], _fetcher(art))
    assert out["status"] == "plan" and out["seam"] == "grounding-registry"
    assert out["crystals"][0]["requires"] == ["compute.local", "store.read"]   # derived from the crystal


def test_capability_gap_is_per_organon_dormant_not_a_whole_crystal_refusal():
    art = crystal_artifact(_crystal(requires=("compute.local", "net.get", "store.read")))
    store = _Capture()
    out = install.install_bundle(_bundle(art), ["compute.local"], _fetcher(art), store=store)
    assert out["status"] == "grounded"                               # the crystal still grounds
    c = out["crystals"][0]
    assert c["lit"] == []
    assert c["dormant"] == [{"organon": "op.respond", "missing": ["net.get", "store.read"]}]  # gap named


def test_measured_prism_object_drives_the_report():
    from prism import Prism, Capability
    art = crystal_artifact(_crystal(requires=("compute.local", "net.get")))
    # `compute.local` carries an explicit probe. `probe=None` means unverified, and an unverified
    # capability is not advertised. A host asserting a structural fact says so with a probe, as
    # ember's `_probe_cpu` does.
    p = Prism([Capability("compute.local", handle=lambda: True, probe=lambda: True),
               Capability("net.get", handle=lambda u: u, probe=lambda: False)])   # net.get dark here
    out = install.install_bundle(_bundle(art), p, _fetcher(art))
    c = out["crystals"][0]
    assert c["lit"] == [] and c["dormant"] == [{"organon": "op.respond", "missing": ["net.get"]}]


def test_an_UNMEASURED_prism_lights_NOTHING():
    """The fail-closed consequence, asserted where an installer would feel it.

    `_advertised()` (`seraph/install.py:80-84`) accepts a Prism or a bare list. A Prism that has
    measured nothing advertises nothing, so every organon reports dormant with its requirements
    named, rather than being lit on a host where no probe ever ran.
    """
    from prism import Prism, Capability
    art = crystal_artifact(_crystal(requires=("compute.local", "net.get")))
    p = Prism([Capability("compute.local", handle=lambda: True),      # no probe → unverified
               Capability("net.get", handle=lambda u: u)])            # no probe → unverified
    out = install.install_bundle(_bundle(art), p, _fetcher(art))
    c = out["crystals"][0]
    assert c["lit"] == []
    assert c["dormant"] == [{"organon": "op.respond", "missing": ["compute.local", "net.get"]}]


def test_tampered_crystal_member_refused():
    art = crystal_artifact(_crystal())
    b = _bundle(art)
    tampered = json.loads(art["content"])
    tampered["organons"].append({"name": "op.evil", "requires": []})
    bad = dict(art); bad["content"] = json.dumps(tampered, sort_keys=True)
    with pytest.raises(ValueError, match="integrity failure"):
        install.install_bundle(b, ["compute.local", "store.read"], _fetcher(bad))


def test_substituted_crystal_pin_mismatch_refused():
    art = crystal_artifact(_crystal())
    other = crystal_artifact(_crystal(requires=("compute.local",)))   # valid but different structure
    other["name"] = art["name"]
    b = _bundle(art)                                # pins art's sha
    with pytest.raises(ValueError, match="substituted structure"):
        install.install_bundle(b, ["compute.local", "store.read"], _fetcher(other))


def test_missing_crystal_is_a_typed_refusal():
    art = crystal_artifact(_crystal())
    out = install.install_bundle(_bundle(art), ["compute.local", "store.read"], lambda name: None)
    assert out["status"] == "refused" and "not found" in out["reason"]
