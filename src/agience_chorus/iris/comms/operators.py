# Operator code lives in chorus and is distributed as a content-addressed source bundle
# (definitions/build_bundles.py); ember executes it via ember/runner.py, sha-verified before exec.
# There is a single path — no separate copy lives elsewhere.
"""Comms — the guardian↔guardian message primitives for the watch/comms plane.

A guardian (the agent tending a node's ember — Claude on 45, Claude on 71) drops a message to its
own ember; the comms tekton's watch (`node/comms-loop.py`) carries it over the shared plane (a NAS
folder, `_comms/`, presented plaintext so a human can read it too) to the peer's ember, where that
guardian reads it. This module holds the message primitives only — building a message artifact and
converting it to/from the plane's wire form. The store I/O and the plane transport live in the
watch loop (the tekton), the same split fetch.py keeps between the primitive and its dispatch.

A message is an artifact (everything is), of a message-specific content type. It is not knowledge
— it lives in a node's private comms thread, never the shared corpus, so it never pollutes
retrieval.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE

MESSAGE_CT = "application/vnd.agience.message+json"   # the content type for message artifacts
_NODE_RE = re.compile(r"^[0-9a-zA-Z._-]{1,32}$")       # a node id is a short token (EMBER_NODE_ID)


def _short_id(frm: str, to: str, ts: str, subject: str, body: str) -> str:
    """A stable short id = de-dup key. Content-addressed so the same message re-dropped is the same
    id (idempotent ingest), independent of when it is carried."""
    h = hashlib.sha256(("\n".join((frm, to, ts, subject, body))).encode("utf-8")).hexdigest()
    return h[:12]


def message_artifact(*, frm: str, to: str, subject: str, body: str, ts: str,
                     kind: str = "note", ref: Optional[str] = None,
                     author: str = "ember-local") -> Dict:
    """Build a message artifact (unsent). `ts` is a UTC ISO-8601 string the caller supplies (the
    node clock is observer-dependent; the primitive never reads a clock — determinism)."""
    for who in (frm, to):
        if not _NODE_RE.match(who or ""):
            raise ValueError("node id %r must match %s" % (who, _NODE_RE.pattern))
    mid = _short_id(frm, to, ts, subject, body)
    return {
        "id": "msg.%s.%s" % (frm, mid),
        "content_type": MESSAGE_CT,
        "state": "outbound",                      # outbound -> the loop publishes it; inbound on ingest
        "collection_id": "comms.thread",
        "collections": ["comms.thread"],
        "visibility": "private", "no_share": True, "no_promote": True,
        "msg_id": mid, "from": frm, "to": to, "ts": ts, "kind": kind, "ref": ref,
        "subject": subject,
        "context": "message %s->%s: %s" % (frm, to, subject),
        "content": body,
        "created_by": author,
    }


def to_wire(msg: Dict) -> Dict:
    """The artifact -> the plane's plaintext JSON wire form (what lands in `_comms/to-<peer>/`)."""
    return {"id": msg["msg_id"], "from": msg["from"], "to": msg["to"], "ts": msg["ts"],
            "kind": msg.get("kind", "note"), "subject": msg.get("subject", ""),
            "body": msg.get("content", ""), "ref": msg.get("ref")}


def from_wire(w: Dict, *, author: str = "ember-local") -> Dict:
    """A plane wire message -> an inbound message artifact (idempotent id via the same hash)."""
    m = message_artifact(frm=str(w.get("from")), to=str(w.get("to")), subject=str(w.get("subject") or ""),
                         body=str(w.get("body") or ""), ts=str(w.get("ts") or ""),
                         kind=str(w.get("kind") or "note"), ref=w.get("ref"), author=author)
    m["state"] = "inbound"
    return m


def wire_filename(w: Dict) -> str:
    """The plane filename for a wire message: `<compact-ts>-<from>-<id>.json` (README protocol)."""
    ts = re.sub(r"[^0-9TZ]", "", str(w.get("ts") or "")) or "00000000T000000Z"
    return "%s-%s-%s.json" % (ts, w.get("from", "x"), w.get("id", "x"))


# ── organon registration (op.comms.*) — offers only; the loop/genesis does the store+plane I/O ──
_COMMS_OPS = [
    ("op.comms.send", "drop a message from this node's guardian to a peer node — builds a private "
     "message artifact (comms.thread); the comms tekton's watch carries it over the plane"),
    ("op.comms.inbox", "read messages addressed to this node — the inbound comms.thread the watch "
     "ingested from the plane"),
]
_HANDLERS = {"op.comms.send": message_artifact}   # pure build; store write is the loop's job


def register_comms_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _COMMS_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "comms operator %s: %s" % (name, offer),
            "created_by": author}))
    return len(_COMMS_OPS)


def invoke(name: str, arguments: Optional[Dict] = None) -> Dict:
    a = arguments or {}
    if name == "op.comms.send":
        return message_artifact(frm=a["from"], to=a["to"], subject=a.get("subject", ""),
                                body=a.get("body", ""), ts=a["ts"], kind=a.get("kind", "note"),
                                ref=a.get("ref"), author=a.get("author", "ember-local"))
    raise KeyError("op.comms.inbox is served by the watch loop (needs the store); no pure handler for %r" % name)


__all__ = ["MESSAGE_CT", "message_artifact", "to_wire", "from_wire", "wire_filename",
           "register_comms_operators", "invoke"]
