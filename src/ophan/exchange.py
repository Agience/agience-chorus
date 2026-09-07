"""The exchange agreement — value crosses between two Origins only through a signed agreement (P7).

[PEERING-AND-MESSAGING §"peering is Origin↔Origin" · UNIVERSAL-ECONOMICS §"the couplings + the
membrane are where ethics attach".]

## Why peering is Origin↔Origin, and why it needs its own artifact

`mass`/`demurrage`/`settlement` are amoral physics — they conserve and dissipate energy but say
nothing about *whether two economies should trade at all, on what terms, or which of the other side's
claims to believe*. That is a governance decision, and governance lives at the Origin (the entity
that owns an Authority and sets the constants — see `origin.py`). So value crossing an origin
boundary is gated by an exchange agreement: a `vnd.agience.exchange+json` that both origins staked.

It carries the three things physics cannot supply:

* **cross-issuer trust** — each party's Authority (issuer), recorded so a signal from origin A,
  validated against A's issuer, is trusted by B *because the agreement says so*. Without this, B has
  no reason to believe A's provenance rungs.
* **the membrane** — what may flow (`allow`): the intersection of the two origins' policies. Isolation
  is the default; every permitted flow is an explicit, auditable grant.
* **the terms** — the flat facilitation fee each side charges on settlement (`settlement.facilitation_split`).

This module builds and resolves the artifact; the actual cross-origin transport and the live slash
stay gated (they need a second live origin and touch the mesh). Like `origin.py`, an agreement is a
container a *person* staked, so its own provenance is human-authored.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

EXCHANGE_CONTENT_TYPE = "application/vnd.agience.exchange+json"

# ophan reads economy constants from the Origin artifact rather than importing origin: an Origin
# artifact is data on the wire, and reading data is not importing code. What this module needs from
# an origin is two reads of a `vnd.agience.origin+json` document the store already holds — its
# `economy` block and its `issuer`. Both are read here, off the artifact, with no default table and
# no governable whitelist: a constant absent from the artifact is ungoverned, and this module
# answers `None`. Origin writes the artifact (`origin/entity.py` keeps `origin_artifact` /
# `register_origin`); ophan only reads it.
#
# ophan does not mint origin ids: an `origin_ref` is used as given, the id the Origin artifact
# carries, rather than run through a slugging rule that would duplicate id-derivation for Origin
# artifacts across two repos and let them drift. An unresolvable ref reads as an origin nobody
# registered, which is what it is, rather than as a fee of zero.
ORIGIN_CONTENT_TYPE = "application/vnd.agience.origin+json"     # the wire type, not a code import


def _canonical_pair(a: str, b: str) -> Tuple[str, str]:
    """Order the two origins deterministically so the same pair yields the same agreement id from
    either side — an agreement is symmetric; A↔B and B↔A are one artifact, never two."""
    a, b = str(a), str(b)
    return (a, b) if a <= b else (b, a)


def exchange_id(a: str, b: str) -> str:
    lo, hi = _canonical_pair(a, b)
    return "urn:agience:exchange:%s::%s" % (lo, hi)


def exchange_artifact(origin_a: str, origin_b: str, *,
                      issuers: Optional[Dict[str, str]] = None,
                      allow: Optional[dict] = None,
                      fee_a: Optional[float] = None, fee_b: Optional[float] = None,
                      owner: str = "") -> Dict[str, Any]:
    """A `vnd.agience.exchange+json` between two Origins.

    `origin_a` / `origin_b` are Origin **ids**, used exactly as given — ophan does not mint them (see
    the module header). `issuers` maps each origin id → the Authority (issuer) the OTHER side agrees
    to trust for it; unpinned, it is resolved from that origin's own artifact at read time, not
    guessed here. `allow` is the membrane (what may flow). `fee_a`/`fee_b` are each side's flat
    facilitation fee; unrecorded, each falls back to that origin's governed `facilitation_fee` and
    then to `None`. Two distinct origins are required — an origin does not sign an exchange
    agreement with itself."""
    # Provenance rungs + the system-citation anchor + `_now` are the stable grounding surface
    # (`prism.grounding`), single-sourced there; `ember.genesis` merely re-exports them. Reaching them
    # through prism keeps ophan off ember — chorus must not import the runner.
    from prism import grounding
    a = str(origin_a)
    b = str(origin_b)
    if a == b:
        raise ValueError("an exchange agreement needs two DISTINCT origins; got %r twice" % a)
    lo, hi = _canonical_pair(a, b)
    fees = {}
    if fee_a is not None:
        fees[a] = float(fee_a)
    if fee_b is not None:
        fees[b] = float(fee_b)
    return {
        "id": exchange_id(a, b),
        "content_type": EXCHANGE_CONTENT_TYPE,
        "state": "committed",
        "parties": [lo, hi],                    # canonical order — symmetric, one artifact per pair
        "issuers": dict(issuers or {}),         # cross-issuer trust: origin_id → agreed Authority
        "allow": allow or {},                   # the membrane: what may flow (default: nothing)
        "fees": fees,                           # origin_id → its flat facilitation fee (default: its own)
        "context": "exchange %s ↔ %s" % (lo, hi),
        "content": "",
        "provenance": grounding.P_HUMAN,
        "cited_from": grounding.CITE_GENESIS,
        "created_by": owner or lo,
        "created_time": grounding._now(),
    }


def register_exchange(store, origin_a: str, origin_b: str, **kw) -> Dict[str, Any]:
    """Write an exchange agreement. Returns it (with `published`)."""
    doc = exchange_artifact(origin_a, origin_b, **kw)
    try:
        (getattr(store, "artifacts", None) or store).put_artifact(doc)
        doc["published"] = True
    except Exception as e:
        doc["published"] = False
        doc["publish_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return doc


# ── resolution ────────────────────────────────────────────────────────────────────────────────────
def _get(store, xid: str) -> Optional[dict]:
    try:
        return (getattr(store, "artifacts", None) or store).get_artifact(xid)
    except Exception:
        return None


# ── reading the Origin artifact (D2) ──────────────────────────────────────────────────────────────
def _origin_doc(store, origin_ref: str) -> Optional[dict]:
    """The `vnd.agience.origin+json` an Origin id resolves to, or `None`.

    A missing artifact carries no default: everything downstream returns `None` when this does, so
    an origin nobody registered settles nothing and trusts no issuer, instead of inheriting a fee or
    an authority from a table shipped in code.
    """
    doc = _get(store, str(origin_ref))
    if isinstance(doc, dict) and doc.get("content_type") == ORIGIN_CONTENT_TYPE:
        return doc
    return None


def governed_constant(store, origin_ref: str, name: str) -> Optional[float]:
    """One of the α's an Origin governs, read off its artifact's `economy` block — or `None`.

    `None` is not `0.0`, and the distinction is the whole point. A governed value of zero is a
    decision someone recorded; an absent one is nobody having decided. There is no inherited-default
    dict here and no whitelist of governable names: the caller names the constant it needs, and the
    artifact either carries it or does not.
    """
    doc = _origin_doc(store, origin_ref)
    econ = doc.get("economy") if doc else None
    if not isinstance(econ, dict):
        return None
    v = econ.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def governing_authority(store, origin_ref: str) -> Optional[str]:
    """The Authority (issuer id / `iss`) an Origin validates against, read off its artifact.

    `None` when the origin, or its `issuer` field, is absent — fail closed: an origin whose
    authority cannot be resolved is one whose tokens must not be validated against a guess."""
    doc = _origin_doc(store, origin_ref)
    return (doc.get("issuer") or None) if doc else None


def agreement_between(store, origin_a: str, origin_b: str) -> Optional[dict]:
    """The exchange agreement for a pair of origins, or None if they have not peered.
    None is the default and the safe one: no agreement ⇒ no value crosses (isolation by default)."""
    a = str(origin_a)
    b = str(origin_b)
    doc = _get(store, exchange_id(a, b))
    if doc and doc.get("content_type") == EXCHANGE_CONTENT_TYPE:
        return doc
    return None


def parties_of(store, xid: str) -> List[str]:
    doc = _get(store, xid)
    if doc and doc.get("content_type") == EXCHANGE_CONTENT_TYPE and isinstance(doc.get("parties"), list):
        return [str(p) for p in doc["parties"] if p]
    return []


def permits(agreement: dict, flow: str) -> bool:
    """Does this agreement's membrane permit `flow`? Fail closed: anything not explicitly allowed is
    denied, and a malformed/None agreement permits nothing. `allow` may list flows (`{"content": true}`
    or `["content", ...]`); a truthy `{"*": true}` opens the membrane fully (an explicit choice)."""
    if not isinstance(agreement, dict) or agreement.get("content_type") != EXCHANGE_CONTENT_TYPE:
        return False
    allow = agreement.get("allow")
    if isinstance(allow, dict):
        if allow.get("*"):
            return True
        return bool(allow.get(flow))
    if isinstance(allow, (list, tuple, set)):
        return "*" in allow or flow in allow
    return False


def fee_for(store, agreement: dict, origin_ref: str) -> Optional[float]:
    """The flat facilitation fee a party charges under this agreement — its recorded fee, else its
    own Origin-governed `facilitation_fee`, else `None`: nobody has set one.

    `facilitation_fee` is governable but has no inherited value, so on an origin that governs no fee
    — the ordinary case for a newly registered one — this returns `None` rather than a default.
    `None` is not `0.0`: a governed fee of zero is a decision someone made, while an absent fee is
    nobody having decided. Returning `0.0` here would silently settle every exchange at no fee under
    the authority of a value nobody set. The caller must handle `None` — decline to settle, or ask
    governance — and it cannot do that if this answers for it. A missing Origin artifact reaches the
    same `None` by the same route: `governed_constant` returns nothing rather than inventing a value.

    There are no callers in production today — the only references are this module's `__all__` and
    three tests — so widening the return type breaks nothing."""
    oid = str(origin_ref)
    fees = agreement.get("fees") if isinstance(agreement, dict) else None
    if isinstance(fees, dict) and oid in fees and isinstance(fees[oid], (int, float)):
        return float(fees[oid])
    return governed_constant(store, oid, "facilitation_fee")


def trusts_issuer(store, agreement: dict, origin_ref: str) -> Optional[str]:
    """The Authority (issuer) the agreement says to trust for `origin_ref`. Falls back to the
    origin's own recorded authority — read off its artifact by :func:`governing_authority` — when
    the agreement does not pin one, and returns None (never guesses) if neither is recorded: no
    agreed authority ⇒ do not trust."""
    oid = str(origin_ref)
    issuers = agreement.get("issuers") if isinstance(agreement, dict) else None
    if isinstance(issuers, dict) and issuers.get(oid):
        return str(issuers[oid])
    return governing_authority(store, oid)


def valid(store, agreement: dict) -> bool:
    """Is this a well-formed, resolvable agreement? Both parties present and distinct, and both
    resolve to a trusted Authority (fail closed — an agreement whose parties cannot be validated is
    not one you may settle across)."""
    if not isinstance(agreement, dict) or agreement.get("content_type") != EXCHANGE_CONTENT_TYPE:
        return False
    parties = agreement.get("parties")
    if not isinstance(parties, list) or len(parties) != 2 or parties[0] == parties[1]:
        return False
    return all(trusts_issuer(store, agreement, p) for p in parties)


__all__ = ["EXCHANGE_CONTENT_TYPE", "ORIGIN_CONTENT_TYPE", "exchange_id", "exchange_artifact",
           "register_exchange", "agreement_between", "parties_of", "permits", "fee_for",
           "governed_constant", "governing_authority", "trusts_issuer", "valid"]
