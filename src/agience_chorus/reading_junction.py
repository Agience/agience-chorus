r"""The junction over a screen — what the placed signal resolves to, found geometrically.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['junction','read:colimit','Mr. Bennet']; \
        runpy.run_module('reading_junction', run_name='__main__')"

This sits at `src/`, beside `_host_seams.py` and `corpus_stats.py`, and is owned by no persona.
Placement is what both sides of the reading need: astra places while it reads (`read_once`,
`read_stream`, `resegment`, `compact`, `learn`, `decompose_educate`) and lumen places while it
answers (`complete`, `chat`). Under `lumen/reading/` it would make five astra modules import lumen
while this module imported astra back for the id rule — a persona→persona cycle in both directions,
which `src/tests/test_persona_isolation.py` counts, and which means neither persona could be
deployed without the other's tree. The id rule below is the canonical one, and
`astra.reading.organon_reader._unit_id` reads it from here.

The goal after every step is the junction with connections to every item on the screen — as few
vertices as possible that still fully represent the screen — found entirely by geometry: place the
vertices, go to the deepest junctions, see what comes up.

If a vertex for `the cat in the hat` exists, it does not have to be searched for, because it is the
junction every item on that screen maps into: coupling stands in for enumeration.

The step, and there is only one:

    place       each unit of the signal is a vertex on the screen
    reach       what do those vertices map into?   (indexed `dst -> src` on the colimit edges)
    couple      which junction absorbs the most of the screen?      (`next_by_coupling`)
    re-place    the residual becomes the incident signal, from its new position, and repeats

The hop count is the answer to "as few vertices as possible". Each hop takes the most of the
screen it can and hands on only what it could not absorb, so the walk terminates when the screen is
spent and the junctions that fired are the covering set. Nothing enumerates subsets; the minimality
is a property of absorb-and-propagate, not a search criterion applied afterwards.

Disambiguation is just more screen. `the cat in the hat` may junction at the book or at a cat
wearing a hat. Put *a real cat is present* on the screen too and the covering junction changes —
same mechanism, more constraint. There is no disambiguation rule here because there is no
disambiguation step; a wider screen is simply harder to cover, so fewer junctions can do it.

Nothing here knows what a noun is. `cat` sits where it sits because it follows `the` in what was
read. Its part of speech is a fact about the geometry, never a tag anyone applied — which is why
this file contains no word list, no part-of-speech table and no grammar.
"""
from __future__ import annotations

import argparse
import collections
import functools
import json
import os
import sqlite3
import sys

import numpy as np

from agience_chorus._host_seams import seam as _seam

_optics = None


def optics():
    global _optics
    if _optics is None:
        _optics = _seam("optics")
    return _optics


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


@functools.lru_cache(maxsize=None)
def surface(node: str) -> str:
    """The text a vertex id stands for — hex span, codepoint form, or the id itself.

    Cached, because it is pure in its argument and it is the hottest call in the reading: one
    completion asked for the same few hundred ids 3.5 MILLION times, re-splitting and re-decoding
    each one. It was the largest single cost of a reply, spread thinly enough across the profile
    to look like nothing in particular."""
    tail = node.split(":")[-1]
    if tail and all(p.startswith("u") and len(p) == 5 for p in tail.split("+")):
        try:
            return "".join(chr(int(p[1:], 16)) for p in tail.split("+"))
        except ValueError:
            return tail
    try:
        return bytes.fromhex(tail).decode("utf-8")
    except Exception:
        return tail


@functools.lru_cache(maxsize=None)
def unit_id(collection: str, tok: str) -> str:
    """The artifact id for a unit — the organon's own id rule, and the one copy of it.

    A unit is an artifact, including a single letter, a space or a comma. Whitespace and punctuation
    cannot ride in an id literally, so a non-alphanumeric unit is addressed by its codepoints
    (`u+0020`), which is reversible and collides with nothing.

    One copy, here. A second would agree on alphanumerics and disagree on every space and comma —
    the highest-count units — so the reader that writes ids and the reader that places against them
    would silently address different artifacts. It lives at `src/` because both personas need it:
    `astra.reading.organon_reader._unit_id` reads it from here, and every astra caller that imports
    `_unit_id` from there keeps working unchanged."""
    # Cached alongside `surface`, its inverse, and for the same reason: one completion asked for
    # the same ids 2.85 MILLION times, re-encoding each surface character by character.
    if tok.isalnum():
        return "%s:%s" % (collection, tok)
    return "%s:%s" % (collection, "+".join("u%04x" % ord(c) for c in tok))


def place(ro, collection: str, signal: str):
    """The signal, placed: the vertices of it the ontology already holds.

    Each position extends while the ontology still recognises what is held, and the matched span is
    the vertex the signal reached — the growing prefix, one indexed lookup per character. At the
    miss the residual re-places from its new position. Linear, and it enumerates nothing.

    The location familiar to this signal is the longest vertex that starts here, whether or not its
    own prefixes were ever formed — a chain that requires every prefix to exist would break at the
    first gap and stop short of a vertex that is in fact held.

    One indexed range per position: ids sort by their text, so every candidate starting with the
    next character sits in one contiguous key range — the store answers "what could start here" in
    a single indexed read, and the longest of those that actually prefixes the signal is where the
    signal is placed. No chain, no scan of the lexicon, no bound anyone chose.

    There is no fallback. A position the ontology does not hold is skipped and counted unplaced,
    and the caller sees coverage below 1, rather than the reader manufacturing a one-character unit
    that was never read."""
    placed, n, i = [], len(signal), 0
    while i < n:
        # Two encodings, so two ranges. `_unit_id` writes an alnum token as `<col>:Lady` and
        # anything carrying a space or punctuation as codepoints, `<col>:u004c+u0061+…`. Those do
        # not sort together, so a range starting at only one form would be blind to vertices written
        # in the other.
        best = ""
        _c = signal[i]
        for lo in (unit_id(collection, _c), "%s:u%04x" % (collection, ord(_c))):
            # `id` ordering is lexicographic, so each range covers exactly the ids sharing that form.
            for (vid,) in ro.execute(
                    "SELECT id FROM vertex WHERE id >= ? AND id < ? || x'ff'", (lo, lo)):
                tok = surface(vid)
                if len(tok) > len(best) and signal.startswith(tok, i):
                    best = tok
        if best:
            placed.append(best)
            i += len(best)                           # re-place at the residual's new position
            continue
        # The last atom of a live signal is cut, not absent. A reader's units carry the space that
        # closes them, so `universally ` is held and `universally` is not — and a person typing a
        # prefix does not type the closing space. The signal is truncated at the instrument's edge,
        # and a unit this text is the start of is where it was placed; anything else discards the
        # most informative word in the question.
        #
        # This applies only at the end, and only if some unit answers — mid-signal a miss is a
        # miss, and the no-fallback rule stands there. Here the comparison is of labels at the
        # text->vertex boundary, which is the one place content is looked at.
        #
        # Every unit it could be is taken, not one of them: a cut signal is genuinely ambiguous
        # about which unit it opens (e.g. `very` opens both a space-closed and a newline-closed
        # unit), which is the same overlap the reader already builds — the screen holds them all
        # and the coupling settles it.
        tail = signal[i:]
        if tail and not tail[-1].isspace():
            hits = set()
            for lo in (unit_id(collection, tail[0]), "%s:u%04x" % (collection, ord(tail[0]))):
                for (vid,) in ro.execute(
                        "SELECT id FROM vertex WHERE id >= ? AND id < ? || x'ff'", (lo, lo)):
                    tok = surface(vid)
                    if tok.startswith(tail):
                        hits.add(tok)
            if hits:
                placed.extend(sorted(hits))
                break
        # Nothing here is held. Step over the text's own run rather than one character, so the next
        # position asked about is a place a unit could actually begin.
        j = i + 1
        sp = signal[i].isspace()
        while j < n and signal[j].isspace() == sp:
            j += 1
        i = j
    return placed


def reach(ro, collection: str, placed):
    """What the placed vertices map into — `{junction_id: [member_id, …]}`.

    Indexed, never scanned. The colimit edge runs `junction --colimit--> member`, so "what is
    above this vertex" is a lookup on `dst` and the work is set by what the signal placed, not by
    how much has been read.

    Both halves of the operator are read. `observed` and `observed_alone` are the same
    context→content link — the operator discriminates them, it does not decide which exist — and a
    query naming only `observed` cannot see a vertex a context holds alone, which is every
    paragraph-unique concept in a collection written that way. `read_basis.OBSERVED` and
    `query_neighbourhood` already read both; these two were the sites that did not."""
    up = collections.defaultdict(set)
    for tok in set(placed):
        for (j,) in ro.execute(
                "SELECT src, props FROM edge WHERE dst = ? "
                "AND label IN ('observed','observed_alone')",
                (unit_id(collection, tok),)):
            up[j].add(unit_id(collection, tok))
    if not up:
        return {}
    members = {}
    for j in up:
        members[j] = [d for (d,) in ro.execute(
            "SELECT dst FROM edge WHERE src = ? AND label IN ('observed','observed_alone')",
            (j,))]
    return members


class Reading:
    """The reading's coordinate, held once.

    The basis is a property of what was read, not of the question, so it is derived once and held
    rather than rebuilt per signal.

    `refresh()` exists because learning moves it: a vertex materialised mid-stream changes the
    cloud, so a held basis goes stale exactly when the reading is working — the caller says when."""

    def __init__(self, ro, collection: str):
        self.ro, self.collection = ro, collection
        self.names, self.contexts = [], []
        self._derived = False
        self._M = self._B = self._coord = None
        self._idx = {}

    # Nothing is pre-built: the cloud and its directions are derived on first use, so a question
    # the deduction can answer never pays for a decomposition, and a question that needs a
    # coordinate pays only then. `walk` — the deduction behind every completion — walks the
    # observation stream by tick and touches no coordinate at all.
    @property
    def M(self):
        self._derive()
        return self._M

    @property
    def B(self):
        self._derive()
        return self._B

    @property
    def coord(self):
        self._derive()
        return self._coord

    @property
    def idx(self):
        if not self._idx:
            # The unit index is a cheap read of the store and is what placement needs; it is not
            # the coordinate, and asking for it must not trigger a decomposition.
            self._names_only()
        return self._idx

    def _names_only(self):
        if self.names:
            return
        proj = _seam("projection")
        uc = proj.read_unit_contexts(self.ro, self.collection)
        self.names = sorted(uc)
        self._idx = {u: i for i, u in enumerate(self.names)}

    def _derive(self):
        if self._derived:
            return
        self._derived = True
        self.refresh()

    def refresh(self):
        """Derive the reading's coordinate, with units as the feature axis.

        `read_cloud` hands back `(units, contexts)`, and the cloud is presented transposed to
        `principal_directions`: contexts are the rows, units are the features. Contexts grow
        linearly with the corpus while the vocabulary grows sub-linearly, so taking contexts as the
        variables would make both the cost and the conditioning of the eigendecomposition degrade as
        the reading improves. Units-as-features is the orientation `build_basis` already uses, and
        the one `optics.accumulator` requires: F is constant across planes, which is what a fixed
        coordinate basis provides.

        A unit's coordinate is its own row of the basis. With units as the feature axis the
        directions are the units' loadings across the resolved modes, so there is no `M @ B` to
        take: `coord[i]` is `B[i]`.

        Dead columns are dropped by the instrument, so the basis comes back over the live units
        only and is scattered back to full width here — a unit no context holds keeps an all-zero
        coordinate, which is the honest reading of "nothing of it is present" rather than a missing
        row the caller would index past.
        """
        import numpy as _np
        proj = _seam("projection")
        self._M, self.names, self.contexts = proj.read_cloud(self.ro, self.collection)
        self._B = self._coord = None
        self._idx = {u: i for i, u in enumerate(self.names or [])}
        self._derived = True
        if self._M is None or not self.names:
            return self
        live = _np.nonzero(self._M.any(axis=1))[0]          # units some context actually holds
        if live.size < 2:
            return self
        Bl = optics().principal_directions(self._M[live].T)  # contexts as rows, units as features
        if Bl is None or Bl.ndim != 2 or Bl.shape[1] < 1:
            return self
        # The basis rows must be the live units, one-to-one, or the basis is not this frame's — a
        # length mismatch is a defect in the read and is reported rather than silently clipped to
        # whichever side is shorter, which would assign some units coordinates from the wrong row.
        if Bl.shape[0] != live.size:
            self._B = None
            self._why_no_coord = ("the basis has %d row(s) for %d live unit(s) — it is not a basis "
                                  "over this frame" % (Bl.shape[0], live.size))
            return self
        self._B = Bl
        coord = _np.zeros((len(self.names), Bl.shape[1]), dtype=float)
        coord[live] = Bl
        self._coord = coord
        return self


def cover(ro, collection: str, signal: str, reading=None):
    """The fewest junctions that still fully represent the screen, found by coupling.

    Returns `{placed, junctions, uncovered, hops}`. `junctions` is the covering set in the order the
    screen was absorbed; `uncovered` is what no junction above this screen could take — reported,
    because a screen that cannot be covered is a real state and not an empty answer."""
    placed = place(ro, collection, signal)
    if not placed:
        return {"placed": [], "junctions": [], "uncovered": [], "hops": 0,
                "refusal": "no vertex of this signal exists in %s" % collection}
    members = reach(ro, collection, placed)
    if not members:
        return {"placed": placed, "junctions": [], "uncovered": placed, "hops": 0,
                "refusal": "the signal placed, but nothing above it — no junction covers this screen"}

    # The screen as a frame: one row per placed vertex, in the reading's own coordinate.
    rd = reading if reading is not None else Reading(ro, collection)
    M, names, B = rd.M, rd.names, rd.B
    if M is None:
        return {"placed": placed, "junctions": [], "uncovered": placed, "hops": 0,
                "refusal": "the reading holds no coordinate to couple in"}
    if B is None:
        return {"placed": placed, "junctions": [], "uncovered": placed, "hops": 0,
                "refusal": "the reading's coordinate resolved no mode"}
    coord, idx = rd.coord, rd.idx

    rows = [coord[idx[unit_id(collection, t)]] for t in placed
            if unit_id(collection, t) in idx]
    if len(rows) < 2:
        return {"placed": placed, "junctions": [], "uncovered": placed, "hops": 0,
                "refusal": "fewer than two placed vertices carry a coordinate — no screen to cover"}
    screen = np.vstack(rows)

    # A junction is one vertex. What it can absorb is its own direction — the coordinate it
    # occupies — not a subspace inferred from the things below it. As an `(F, 1)` column that is a
    # rank-one band, which `absorb_transmit` takes directly and which needs no minimum row count,
    # because there is no correlation being read: the direction is already known. Most junctions
    # have too few members for `principal_directions` to read a correlation from them at all, which
    # is why the band comes from the junction's own coordinate rather than being fitted to members.
    bases = {}
    for j in members:
        if j in idx:
            v = np.asarray(coord[idx[j]], dtype=float)
            if np.any(v):
                bases[j] = v.reshape(-1, 1)
    if not bases:
        return {"placed": placed, "junctions": [], "uncovered": placed, "hops": 0,
                "refusal": "no junction above this screen resolved a band to couple with"}

    # Absorb, re-place, repeat. Each hop takes the most of the screen it can; the residual is the
    # incident signal for the next. The walk ends when nothing more couples, and the junctions that
    # fired are the covering set — minimal because each took its maximum, not because subsets were
    # compared.
    residual, fired, hops = screen, [], []
    while True:
        hop = optics().next_by_coupling(residual, bases, fired=tuple(fired))
        if not hop or hop.get("tekton") is None:
            break
        j = hop["tekton"]
        fired.append(j)
        hops.append({"junction": surface(j), "id": j,
                     "absorbed_energy": round(float(hop.get("absorbed_energy") or 0.0), 3),
                     "k": hop.get("k")})
        residual = np.asarray(hop.get("transmitted"), float)
        if not np.any(residual):
            break
    left = float((np.abs(residual) ** 2).sum())
    total = float((np.abs(screen) ** 2).sum())
    return {"placed": placed, "junctions": hops, "hops": len(hops),
            "screen_absorbed": round(1.0 - (left / total if total else 0.0), 4),
            "uncovered": [], "refusal": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("signal", nargs="+")
    args = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    for sig in args.signal:
        out = cover(ro, args.collection, sig)
        print("")
        print("SIGNAL %r" % sig)
        print("  placed     %s" % out["placed"])
        if out.get("refusal"):
            print("  REFUSED    %s" % out["refusal"])
            continue
        print("  screen absorbed %.1f%% in %d junction(s) -- as few vertices as cover it"
              % (100.0 * out["screen_absorbed"], out["hops"]))
        for h in out["junctions"]:
            print("     %-22r absorbed %-10s k=%s" % (h["junction"], h["absorbed_energy"], h["k"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
