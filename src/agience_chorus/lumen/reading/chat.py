r"""The chat responder — talk to what has been read, and choose what that is.

Wired onto aria's bff by the host (`chorus/personas.py::_wire_conversation_carrier`); this module
exports and serves nothing, because `lumen` may not import `aria`.

    /use read:pride        point the chat at a collection
    /collections           what has been read, and how well each reads
    <anything else>        completed from that collection and nothing else

The collection is the data store. A reading is scoped to a collection, so "which corpus am I talking
to" is exactly "which collection". An identified caller picks it with `/use`; an anonymous caller —
every caller of aria's public bff, which passes no identity — talks to `READ_COLLECTION` and nothing
else, and `/use` and `/collections` are refused to it, because they would let a stranger list and
read every `read:*` collection in the store.

State is per caller. An identified caller's selection and screen are kept under that caller's id and
no other caller sees them. An anonymous caller has no id to keep state under, so nothing carries
between its turns: one stranger's conversation must never become the next stranger's context.

Every reply states the collection it came from, how much of the question the reading recognised, and
which act produced it — `deduce` when the reading has walked this path before, `forecast` when it has
not. A completion drawn from a corpus that never contained the question must not look like one that did.

Nothing is composed here. The words are the reading's own vertices, emitted by descending the colimit to
surface; what is generated is the selection and the order. There is no filter that generates prose to
look like an answer, and no scaffold that asserts a reading the store never made.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from collections import OrderedDict

#: Per-caller state: {caller: {"collection", "screen"}}. Bounded; the least recently used caller's
#: state is dropped first.
_STATES: "OrderedDict[str, dict]" = OrderedDict()
_MAX_CALLERS = 1000
#: A collection's reading, cached by collection. It is derived from the store alone — the same for
#: every caller — so sharing it shares no caller's data.
_READINGS: dict = {}
_LOCK = threading.Lock()


def _state_for(caller):
    """The caller's state, or a fresh one for an anonymous caller that is never stored."""
    fresh = {"collection": os.environ.get("READ_COLLECTION") or "", "screen": []}
    if not caller:
        return fresh
    with _LOCK:
        st = _STATES.pop(caller, None) or fresh
        _STATES[caller] = st
        while len(_STATES) > _MAX_CALLERS:
            _STATES.popitem(last=False)
        return st


def _db() -> str:
    # The shard is a data volume, not part of the checkout, so no default here could be right
    # on another box. Unset is REFUSED rather than guessed: a reader silently opening a store
    # nobody chose does not fail, it reports an empty corpus — which reads as "nothing found"
    # when the truth is "nothing configured".
    root = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
    if not root:
        raise RuntimeError(
            "EMBER_SQLITE_DIR is unset. Point it at the directory holding lattice.db.")
    return os.path.join(root, os.environ.get("EMBER_SQLITE_DB", "lattice.db"))


def collections(ro) -> list:
    """Every `read:*` collection in the store, with what it holds. One indexed range, no scan."""
    seen = {}
    for (i,) in ro.execute(
            "SELECT id FROM vertex WHERE id >= 'read:' AND id < 'read;'"):
        c = ":".join(i.split(":")[:2])
        seen[c] = seen.get(c, 0) + 1
    return sorted(seen.items())


def _reading(ro, collection):
    """The collection's coordinate, held across turns — it is a property of the reading, not of the
    question, so deriving it per message would be both slower and a different coordinate each time."""
    import agience_chorus.reading_junction as _j
    with _LOCK:
        rd = _READINGS.get(collection)
    if rd is None:
        rd = _j.Reading(ro, collection)
        if getattr(rd, "idx", None):                 # only a collection that holds something
            with _LOCK:
                _READINGS[collection] = rd
    return rd


def respond(query, caller=None):
    """The carrier contract aria's bff calls: `respond(q) -> dict | None`.

    `caller` is the identified caller's id; None is an anonymous caller, which cannot switch or list
    collections and carries no state between turns."""
    from agience_chorus.lumen.reading import complete as _c
    q = (query or "").strip()
    if not caller and (q.startswith("/collections") or q.startswith("/use")):
        return {"answer": "", "cited": [], "grounded": False, "refused": True,
                "why": "choosing a collection needs an identified caller"}
    st = _state_for(caller)
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    try:
        if q.startswith("/collections"):
            rows = collections(ro)
            if not rows:
                return {"answer": "nothing has been read into this store yet.",
                        "cited": [], "grounded": False, "why": "no read:* collection exists"}
            body = "\n".join("  %-28s %6d artifact(s)" % (c, n) for c, n in rows)
            return {"answer": "collections in this store:\n\n%s\n\nuse one with:  /use <name>"
                              % body,
                    "cited": [c for c, _n in rows], "grounded": True}

        if q.startswith("/use"):
            want = q[4:].strip()
            if not want:
                return {"answer": "name a collection, e.g.  /use read:pride",
                        "cited": [], "grounded": False}
            rd = None
            try:
                rd = _reading(ro, want)
            except Exception:
                rd = None
            # `/use` needs to know the collection holds something, which is one indexed read; how
            # many modes it resolves is a decomposition, and nothing here pre-builds it.
            n_units = len(rd.idx) if rd is not None else 0
            if not n_units:
                return {"answer": "%s holds no unit in any context — nothing has been read into it."
                                  % want,
                        "cited": [], "grounded": False,
                        "why": "the collection holds nothing to read"}
            st["collection"] = want
            return {"answer": "reading %s — %d unit(s).\n"
                              "say anything and it will be completed from this and nothing else."
                              % (want, n_units),
                    "cited": [want], "grounded": True}

        col = st.get("collection")
        if not col:
            if not caller:
                return {"answer": "", "cited": [], "grounded": False,
                        "why": "no collection is configured"}
            rows = collections(ro)
            hint = ("  try:  /use %s" % rows[0][0]) if rows else "  nothing has been read yet."
            return {"answer": "no collection selected.\n%s\n(/collections lists them)" % hint,
                    "cited": [], "grounded": False, "why": "no collection selected"}

        rd = _reading(ro, col)
        if rd is None or not rd.idx:
            return {"answer": "", "cited": [], "grounded": False,
                    "why": "%s holds no unit in any context" % col}

        # The screen persists between turns, and forgets. What the last turns placed and said is
        # still present, which is what makes a question's instrument specific enough to read — one
        # question alone opens too thin a one. It is held to the extent of the exchange itself:
        # the screen keeps as many turns as the conversation has had recently, so it widens while
        # you talk and empties when you stop, rather than growing without bound.
        carried = [v for turn in st.get("screen", []) for v in turn]
        out = _c.complete(ro, col, q, reading=rd, carried=carried)
        turns = list(st.get("screen", []))
        turns.append(out.get("on_screen") or [])
        st["screen"] = turns[-4:]
        said = (out.get("completion") or "").strip()
        acts = [s.get("act") for s in out.get("steps", []) if s.get("act")]
        stopped = next((s.get("stopped") for s in out.get("steps", []) if s.get("stopped")), None)
        if not said:
            # A refusal with its reason and its numbers — never a sentence about being unable to help.
            return {"answer": "", "cited": [col], "grounded": False,
                    "why": stopped or "nothing in %s continues this" % col,
                    "read": {"collection": col, "placed": out.get("placed"),
                             "coverage": out.get("coverage")}}
        return {"answer": said, "cited": [col], "grounded": True,
                "why": None,
                "read": {"collection": col, "act": (acts[0] if acts else None),
                         "coverage": out.get("coverage"),
                         "placed": len(out.get("placed") or []),
                         "stopped": stopped}}
    finally:
        ro.close()
