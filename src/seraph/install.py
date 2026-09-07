"""op.install — the installer organon (OPERATOR-ARCHITECTURE §12.3).

An install bundle is a signed crystal, or a set of them, and nothing else. Install means:

  1. Verify the bundle sha: recompute the canonical payload hash and compare it to the manifest's
     claimed ref; a mismatch raises rather than installing unverified bytes, the same
     refuse-before-grounding rule as `crystal.crystal_model.verify`.
  2. For each crystals[] member: fetch the crystal artifact, verify it with
     `crystal.crystal_model.verify` (refusing tampering loudly), check the member's sha pin matches
     the verified structure, and ground it — recording the structure through the caller's `store`, or
     returning the validated plan.
  3. Report the activation on the prism: a crystal grounds regardless, since structure is portable;
     each organon lights up only if its capabilities are present on the prism. The result carries,
     per crystal, which organons are lit and which are dormant, with the missing capabilities named.
     A capability gap is not a whole-crystal refusal — it is honest per-organon darkness.

A crystal is always "grounded"; there is no other kind of crystal install. Package-manager
provisioning (pip, npm, cmake, compose) is not a crystal install at all — it is environment
provisioning, how a prism acquires a capability (e.g. `pip install` to make `compute.gpu` real), and
belongs to the prism / host-policy layer rather than to this organon. The needed capabilities are
derived from the crystal (`required_capabilities`), never restated in the manifest, so the two cannot
drift apart.

Integrity failures raise, since a tampered bundle is a security event and never negotiable. A missing
crystal is a typed refusal, an honest negotiation. A limited prism is normal: the ember runs with the
organons its prism lights. `prism` is duck-typed: `advertises() -> set[str]` on a built `Prism`, or a
plain capability list. stdlib at import; `crystal.crystal_model` imported lazily.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List
from prism.canonical import canonical_string as _jcs_string

BUNDLE_CONTENT_TYPE = "application/vnd.agience.bundle+json"


# One definition: the rule that decides bundle shas lives in `prism.canonical`, imported here rather
# than restated, since chorus -> prism is a legal dependency direction.
from prism.canonical import canonical_payload  # noqa: F401


def sha256_of(content: Any) -> str:
    return hashlib.sha256(canonical_payload(content)).hexdigest()


def _manifest_of(bundle_artifact: Dict[str, Any]) -> Dict[str, Any]:
    ctx = bundle_artifact.get("context") or "{}"
    manifest = json.loads(ctx) if isinstance(ctx, str) else dict(ctx)
    if not isinstance(manifest, dict):
        raise ValueError("bundle artifact context is not a manifest object")
    return manifest


def verify_bundle(bundle_artifact: Dict[str, Any]) -> Dict[str, Any]:
    """The bundle integrity gate: recompute the payload sha, compare to the claimed ref, raise on
    mismatch. Returns the parsed manifest on success."""
    manifest = _manifest_of(bundle_artifact)
    claimed = manifest.get("sha256")
    content = bundle_artifact.get("content", "")
    actual = sha256_of(content)
    if claimed != actual and isinstance(content, str):
        try:
            actual = sha256_of(json.loads(content))
        except Exception:
            pass
    if claimed != actual:
        raise ValueError("bundle integrity failure: manifest sha256=%s but payload hashes to %s "
                         "— refusing to install unverified bytes" % (claimed, actual))
    return manifest


def _refusal(reason: str, **detail: Any) -> Dict[str, Any]:
    out = {"status": "refused", "reason": reason}
    out.update(detail)
    return out


def _advertised(prism) -> set:
    """The capability set the prism affords — the built `Prism` (measured), or a plain list."""
    if hasattr(prism, "advertises"):
        return set(prism.advertises())
    return set(prism or [])


def install_bundle(bundle_artifact: Dict[str, Any], prism, fetch_crystal, store=None) -> Dict[str, Any]:
    """Install a signed-crystal bundle. See the module docstring for the full contract.

    `prism` — the environment: a built `Prism` (duck-typed `advertises()`), or a capability list.
    `fetch_crystal(name)` -> crystal artifact dict (the store/mantle seam).
    Returns a typed result with per-crystal, per-organon activation. Raises on integrity failure or a
    structurally invalid bundle (loud, never half-load).
    """
    from crystal.crystal_model import crystal_sha, required_capabilities, verify

    manifest = verify_bundle(bundle_artifact)                     # 1. the bundle sha gate

    members = manifest.get("crystals")
    if not isinstance(members, list) or not members:
        raise ValueError("a crystal bundle must list its crystals [{name, sha256}, ...]")

    advertised = _advertised(prism)
    grounded: List[Dict[str, Any]] = []
    for member in members:
        name, pin = member.get("name"), member.get("sha256")
        if not name or not pin:
            raise ValueError("every crystals[] member needs name + sha256 "
                             "(an unpinned crystal cannot refuse tampering)")
        artifact = fetch_crystal(name)
        if not artifact:
            return _refusal("crystal %s not found in the store" % name, crystal=name)
        crystal = verify(artifact)                                # 2. raises on tampering
        if crystal_sha(crystal) != pin:
            raise ValueError("crystal %s: bundle pins sha256=%s but the fetched crystal is %s "
                             "— refusing to ground a substituted structure"
                             % (name, pin, crystal_sha(crystal)))
        # 3. per-organon activation on this prism — a crystal grounds regardless; organons light up
        #    iff their capabilities are present. Partial activation is normal and honest.
        lit, dormant = [], []
        for o in crystal.get("organons") or []:
            miss = sorted(set(o.get("requires") or []) - advertised)
            if miss:
                dormant.append({"organon": o["name"], "missing": miss})
            else:
                lit.append(o["name"])
        grounded.append({"name": name, "sha256": pin,
                         "requires": required_capabilities(crystal),
                         "lit": lit, "dormant": dormant, "artifact": artifact})

    descriptor = {
        "bundle": bundle_artifact.get("name") or bundle_artifact.get("id"),
        "sha256": manifest.get("sha256"),
        "crystals": [{k: g[k] for k in ("name", "sha256", "requires", "lit", "dormant")} for g in grounded],
        "advertised": sorted(advertised),
    }
    if store is not None:
        for g in grounded:
            store.put_artifact(dict(g["artifact"]))               # content-addressed, idempotent
        descriptor["status"] = "grounded"
    else:
        descriptor["status"] = "plan"
        # No crystal-grounding registry exists, so recording the structure is the caller's job,
        # through whatever store surface it owns; the descriptor names the missing seam rather than
        # silently completing the write itself.
        descriptor["seam"] = "grounding-registry"
    return descriptor


# ── registration — op.install ────────────────────────────────────────────────
_INSTALL_OPS = [
    ("op.install", "installs a signed-crystal bundle: verifies the bundle sha, verifies every member "
     "crystal (crystal.crystal_model — refuses tampering), grounds the structure, and REPORTS the "
     "per-organon activation on the prism (lit organons, and dormant ones with the missing capability "
     "named). Environment provisioning is the prism's concern, not this organon's"),
]


def register_install_operators(store, *, author: str = "ember-local") -> int:
    """Register the installer organon. Mirrors the persona register_* pattern."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _INSTALL_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"system operator {name}: {offer}",
            "created_by": author}))
    return len(_INSTALL_OPS)


__all__ = ["BUNDLE_CONTENT_TYPE", "canonical_payload", "sha256_of", "verify_bundle",
           "install_bundle", "register_install_operators"]
