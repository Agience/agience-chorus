r"""Read in order, from empty — the lexicon grows as the stream arrives.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['read_stream','read:s1','--text','<corpus-dir>/_pnp40k.txt', \
                  '--delimit','period']; \
        runpy.run_module('astra.reading.read_stream', run_name='__main__')"

The lexicon starts empty and nothing is precomputed. Each chunk is placed against what the reading
has learned so far, and the colimit forms units as the stream arrives — chunk 400 is read with what
chunks 1-399 taught. That is the difference between learning and re-weighting.

Placement never falls back. A run the reading holds is recognised; a run it does not is admitted at
count zero and earns its count by recurring, exactly as a fresh junction does. So the first chunk is
almost entirely admission, and what the reader reports as recognised is only ever what it had
already been taught.

The delimiter is the text's own, and it is the one choice here. A period, a line, or a blank line —
each is a mark the file supplies, not a claim about English inferred by this module. `--delimit` is
offered because which one the reading should take is a question to measure rather than assert, and
the three are directly comparable when run into separate collections from empty.

No normalising, no stripping, no folding. Case is kept, punctuation is kept, whitespace is kept.
Whitening and normalisation are the screen's, performed by entroptics on the frame, never by a
reader tidying its input — a reader that cleans its text has decided what the text is.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import time

import numpy as _np

TOKEN_CT = "application/x-token"


def chunks(text: str, delimit: str):
    """The stream in the text's own units. Nothing is stripped: the delimiter stays on the chunk it
    ends, because it is part of what was read.

    The whitespace after the delimiter stays with it too, rather than starting the next chunk: a
    space belongs to the run it closes, and leaving it at the start of the next chunk would give
    `atoms()` no preceding run to attach it to, turning a bare space into a standalone unit at
    nearly every chunk. Joining the chunks still reproduces the text exactly."""
    if delimit == "paragraph":
        parts, sep = text.split("\n\n"), "\n\n"
    elif delimit == "line":
        parts, sep = text.split("\n"), "\n"
    else:                                        # period
        parts, sep = text.split("."), "."
    out = []
    for i, p in enumerate(parts):
        s = p + (sep if i < len(parts) - 1 else "")
        if s:
            out.append(s)
    joined = []
    for s in out:
        lead = len(s) - len(s.lstrip())
        if lead and joined:
            joined[-1] += s[:lead]               # the space belongs to the run it closes
            s = s[lead:]
        if s:
            joined.append(s)
    return joined


def atoms(chunk: str):
    """The chunk in the marks the text supplies — its own runs of space and non-space.

    The arrival unit is the word, not the character, and the text is what says so. Whitespace is a
    mark the file contains, the same class of mark as the period `chunks()` already splits on;
    taking it is reading what is there, not asserting a rule about English. Nothing is stripped or
    folded — joining the atoms reproduces the chunk exactly.

    A space is its own atom, not luggage on the word before it. Kept separate, the space is a
    vertex like any other and `universally ` is the colimit of the two — so the reading learns the
    join instead of having it imposed, and a query missing the closing space still places on the
    word. Gluing whitespace onto the preceding run instead would make the trailing space
    load-bearing at query time, since the run without it would never exist as its own vertex.

    Arriving as words rather than characters keeps the lexicon aligned to the text's own
    boundaries. With an empty lexicon and a character floor, the first chunk would place as single
    letters and every unit would be built up from there, so a space would be just another character
    for the colimit to fuse across, forming phrases before it has learned words."""
    out, n, i = [], len(chunk), 0
    while i < n:
        j = i + 1
        sp = chunk[i].isspace()
        while j < n and chunk[j].isspace() == sp:
            j += 1
        out.append(chunk[i:j])
        i = j
    return out


def place_local(seq, lex: dict, longest: int):
    """Place a chunk's atoms against what the reading holds now — longest match, one lookup per run.

    The lexicon is in memory during the read, not the store: placement is the reader's hottest
    path (one lookup per candidate length per position), and the store is written once, at the end,
    from the same lexicon.

    `longest` is counted in atoms. The colimit works upward from there into phrases; it can still
    learn to spell, but only where the reading gives it cause to, rather than because spelling was
    all it was ever handed.

    There is no fallback. An atom that misses at every length comes back `known=False`: the reading
    does not hold it, it is new, and the caller must admit it rather than count it as recognition.
    Falling back to a single atom regardless of whether the lexicon held it would make a word the
    reading held and a word it had never seen look identical, and every chunk would place
    completely — coverage could never report a miss.

    This covers rather than partitions, which is the difference between a colimit and a tiling.
    Every vertex covering a position is returned, with the span it covers, so a long statement
    yields many overlapping vertices — walking greedily and advancing past what was taken would give
    each position exactly one unit, suppressing the evidence a colimit needs: once `AB` forms, `B`
    would be swallowed at that position and the pair `(B,C)` could never be witnessed again. It
    would also give each unit essentially one successor, so walking the graph would hand back the
    contiguous source passage, which is precisely what a colimit exists to prevent.

    Returns `(surface, start, span, known)` in start order, longest cover first at each position."""
    out, n = [], len(seq)
    for i in range(n):
        hi = min(longest, n - i)
        hit = False
        for L in range(hi, 0, -1):
            surf = "".join(seq[i:i + L])
            if surf in lex:
                out.append((surf, i, L, True))
                hit = True
        if not hit:
            out.append((seq[i], i, 1, False))
    return out


def read_stream(store, collection: str, text: str, delimit: str = "period", say=print) -> dict:
    """Read the stream in order, forming units as it goes."""
    from _host_seams import seam as _seam
    from astra.reading.organon_reader import _unit_id

    _optics = _seam("optics")
    bits = _optics.self_information_bits
    at_split = _optics.absorb_transmit
    corr_len = _optics.correlation_length
    t0 = time.time()

    lex = collections.Counter()          # surface -> how often the reading has placed it
    pair_n = collections.Counter()
    # `longest` and `span` are counted in atoms, not characters, because that is the grain
    # placement steps in. A unit's span is how many of the text's own runs it covers, so a
    # junction's span is the sum of its members' — the ladder measures itself in the same unit it
    # was built in.
    span = {}
    longest = 1
    N = 0
    # One edge per (src, dst, label), carrying EVERY measurement true of that pair. The store keys
    # edges by src/dst, so appending two rows for the same pair silently keeps one: measured on the
    # whitespace reading, the pair (junction 'had ' -> member 'had') is BOTH an order edge and a
    # colimit membership, and the order props overwrote the membership. 3,831 junctions (4.5%) lost
    # a member that way, so `outgest` dropped the word entirely when it descended them. Order and
    # membership are different facts about the same pair, not competing edges.
    _edge_props = {}

    def edge(src, dst, label, props):
        k = (src, dst, label)
        cur = _edge_props.get(k)
        if cur is None:
            _edge_props[k] = dict(props)
        else:
            cur.update(props)

    junctions, obs_rows = [], []
    n_chunks = 0
    screen, held, t_glob, fires, widths, leak = [], [], 0, 0, [], None
    formed = set()
    lengths = []
    novel = 0
    neighbours = set()
    # The units placed, in order — handed back so a caller can score the read against the text's own
    # boundaries. Re-deriving this outside the reader would let a probe measure its own
    # re-implementation instead of the reader itself.
    stream = []

    for n, chunk in enumerate(chunks(text, delimit)):
        seq = atoms(chunk)
        cover = place_local(seq, lex, longest)
        # Admitted, not placed. A unit the reading did not hold enters the lexicon at count 0 and
        # earns its count by recurring — the same rule the colimit already uses for a junction it
        # has just formed. So first sight is admission and second sight is recognition, and nothing
        # is ever credited as recognised on the occasion it was learned.
        for surf, _i, _L, known in cover:
            if not known:
                lex[surf] = 0
                span.setdefault(surf, len(atoms(surf)))
                novel += 1
        if not cover:
            continue

        # what starts where — adjacency is by span, so a vertex covering [i, i+L) is followed by
        # every vertex starting at i+L, at every level the reading holds there
        by_start = {}
        for surf, i, L, _k in cover:
            by_start.setdefault(i, []).append((surf, L))

        # the reading's own segmentation, for scoring only: longest cover, walked
        i = 0
        while i < len(seq):
            surf, L = max(by_start.get(i, [(seq[i], 1)]), key=lambda t: t[1])
            stream.append(surf)
            i += L
        lengths.append(len(cover))

        # The step frame — rows are steps, features are the vertices collected at each step. With an
        # overlapping cover a step is a position and it collects every vertex covering it, so the
        # frame is what the reading already produced: one row per position, one column per vertex
        # on this screen. It is small — a sentence, not a corpus — which is what makes an energy
        # measurable per edge without ever building a frame over the whole reading.
        #
        # The screen must hold more than one step or nothing couples at all: built per chunk with
        # one position per row, a position's covering set is nearly unique, so the columns are
        # one-off indicators and the spectrum is flat against the noise bulk. Holding the screen
        # open across steps lets it resolve a direction, because the overlap between consecutive
        # screens is the correlation — one row per position has none.
        #
        # So the screen integrates until the gate opens, and then it fires. How wide the screen
        # gets is neither chosen nor a decay constant — it is how much had to arrive before anything
        # could receive it. `k > 0` is the gate: a direction resolved above the instrument's own noise
        # floor, which is what "a matching dendrite is available" means when the receiver has to be
        # measured rather than declared. On firing the absorbed band is the discharge and the steps
        # that carried it take their energy; what did not couple stays on the screen and keeps
        # integrating, because `‖incident‖² = ‖absorbed‖² + ‖transmitted‖²` holds exactly and the
        # residual is a real remainder, not a reset.
        #
        # A row is what the screen is holding at that step, not what arrived at it. Arrivals at
        # different positions are nearly disjoint, so a frame of arrivals decorrelates row to row
        # and the gate never opens. Cumulative rows overlap by construction, which is the
        # correlation the instrument can resolve and the only thing xi can honestly be measured
        # against.
        arrivals = []
        for _q in range(len(seq)):
            arrivals.append(set())
        for s_, i_, L_, _k in cover:
            for t_ in range(i_, min(i_ + L_, len(seq))):
                arrivals[t_].add(s_)
        base_t = t_glob
        for _q, av in enumerate(arrivals):
            held.append(av)
            if leak is not None and len(held) > leak:
                del held[:len(held) - leak]
            screen.append((t_glob + _q, {v for a in held for v in a}))
        t_glob += len(seq)
        if leak is not None and len(screen) > leak:
            del screen[:len(screen) - leak]

        step_e = {}                                    # global step -> absorbed energy, once fired
        cols = sorted({v for _t, r in screen for v in r})
        if len(screen) > 1 and len(cols) > 1:
            at_col = {c: j for j, c in enumerate(cols)}
            deg = collections.Counter(v for _t, r in screen for v in r)
            tot = float(sum(deg.values()))
            amp = {}
            for c in cols:
                b = bits(float(deg[c]), tot)
                amp[c] = float(_np.sqrt(b)) if b and b > 0.0 else 0.0
            F = _np.zeros((len(screen), len(cols)), dtype=float)
            for r_, (_t, vs) in enumerate(screen):
                for v in vs:
                    F[r_, at_col[v]] = amp[v]
            # Leak, and its extent is measured on the frame itself. Integrate-and-fire with no leak
            # is unbounded, since the screen keeps growing as long as nothing fires. xi is the
            # attenuation scale this instrument reads off this frame — past it the screen no longer
            # correlates with itself, so those steps are being carried rather than held. It sets how
            # much the screen keeps from here on; when xi cannot be read nothing is trimmed to a
            # guess.
            xi = corr_len(F)
            if xi is not None and xi == xi and xi >= 1.0:
                leak = int(xi)
            split = at_split(F)
            if split is not None and int(split[2]) > 0:            # the gate opened - fire
                absorbed, transmitted = split[0], split[1]
                e_row = (_np.abs(absorbed) ** 2).sum(axis=1)
                r_row = (_np.abs(transmitted) ** 2).sum(axis=1)
                fires += 1
                widths.append(len(screen))
                for r_, (t_, _vs) in enumerate(screen):
                    step_e[t_] = float(e_row[r_])
                # Discharge: a step that gave up more than it kept has been received; one still
                # carrying more than it gave has not, and stays on the screen as the residual.
                screen = [row for r_, row in enumerate(screen) if r_row[r_] > e_row[r_]]

        # The observation is a colimit over its own path — a sentence is a colimit of its words
        # exactly as `the cat ` is a colimit of `the ` and `cat `, so it needs no second relation
        # and no stored copy of its text. As a colimit the observation is a real vertex that
        # context can attach to, its members are its ordered path, and its surface is recovered by
        # descending them rather than looked up.
        oid = "%s:obs-%d" % (collection, n_chunks)
        n_chunks += 1
        top = []
        i = 0
        while i < len(seq):
            s_, L_ = max(by_start.get(i, [(seq[i], 1)]), key=lambda t: t[1])
            top.append((s_, i))
            i += L_
        c_obs = bits(1.0, float(N + 1))
        c_mem = [bits(float(max(lex[s_], 1)), float(N + 1)) for s_, _t in top]
        if c_obs is not None and all(c is not None for c in c_mem):
            saved_obs = float(sum(c_mem) - c_obs)
            obs_rows.append({
                "id": oid, "content_type": TOKEN_CT, "name": oid.split(":")[-1],
                "collection_id": collection, "collections": [collection],
                "created_by": "ember-source", "at": n_chunks - 1,
                "length": len(chunk), "members": len(top), "bits_saved": saved_obs,
            })
            # The observation holds every vertex covering it, rather than its top-level path alone.
            # Linking the top path alone leaves a base word with almost no context of its own —
            # `Bennet` shows three on a reading that uses it hundreds of times — so every context
            # question climbs the ladder and comes back with the contexts of the junctions above the
            # word instead of the word's own, leaving the context sets available to the completion
            # either too narrow to say anything or too wide to distinguish
            # anything, with nothing in between. A position belongs to every vertex covering it,
            # which is what the cover already computed; this records it.
            for s_cov in dict.fromkeys(s for s, _i, _L, _k in cover):
                edge(oid, _unit_id(collection, s_cov), "observed", {"in": 1})
            for at_m, (s_, t_) in enumerate(top):
                pr = {"bits_saved": saved_obs, "at": at_m}
                if (base_t + t_) in step_e:
                    pr["energy"] = step_e[base_t + t_]
                edge(oid, _unit_id(collection, s_), "observed", pr)

        for surf, _i, _L, known in cover:
            if not known:
                continue                          # admitted this chunk; it earns its count by recurring
            N += 1
            lex[surf] += 1
            if surf not in span:                  # atoms() is a scan; ask it once per surface
                span[surf] = len(atoms(surf))
            if span[surf] > longest:
                longest = span[surf]

        # The colimit forms as the counts cross — cheaper than its parts, and recurred. It runs over
        # adjacent covering vertices at every level, so one statement fuses at several scales at
        # once.
        for a, ia, La, _ka in cover:
            for b, _Lb in by_start.get(ia + La, ()):
                # The neighbour relation, written down: `b` was read immediately after `a`. Without
                # this edge a unit's context is bag-of-sentence via `observation -> unit`, and the
                # colimit pair alone is not a substitute, since it keeps a pair only if it recurred
                # and beat the information cost, discarding most adjacency at read time. The order
                # edge is what lets a continuation be read geometrically, off neighbours, rather
                # than off stored text.
                if (a, b) not in neighbours:
                    neighbours.add((a, b))
                    # The force the edge carries is a share of a conserved quantity: the
                    # information cost decides whether the colimit fuses, but `energy` is the
                    # absorbed band at the step this order was witnessed — and absorbed sums with
                    # the residual to the incident exactly, so two edges out of one vertex are
                    # dividing something real instead of both reporting a large unrelated number.
                    pr = {"next": 1}
                    tb = base_t + ia + La
                    if tb in step_e:
                        pr["energy"] = step_e[tb]
                    edge(_unit_id(collection, a), _unit_id(collection, b), "observed", pr)
                pair_n[(a, b)] += 1
                k = pair_n[(a, b)]
                joined = a + b
                # both members must have recurred — a member still at count 0 was admitted, not
                # recognised, and there is no information in fusing onto something never seen twice.
                if k < 2 or joined in lex or joined in formed or lex[a] < 1 or lex[b] < 1:
                    continue
                c_j, c_a, c_b = (bits(float(k), float(N)), bits(float(lex[a]), float(N)),
                                 bits(float(lex[b]), float(N)))
                if None in (c_j, c_a, c_b) or c_j >= (c_a + c_b):
                    continue
                formed.add(joined)
                lex[joined] = 0                       # it exists now; it earns its count by recurring
                span[joined] = span.get(a, 1) + span.get(b, 1)
                longest = max(longest, span[joined])
                saved = float((c_a + c_b) - c_j)
                vid = _unit_id(collection, joined)
                junctions.append({
                    "id": vid, "content_type": TOKEN_CT, "name": joined, "content": joined,
                    "collection_id": collection, "collections": [collection],
                    "created_by": "ember-source", "length": len(joined),
                    "witnesses": int(k), "bits_saved": saved,
                })
                # Which member came first is a fact the reader witnessed, so it is written down as
                # an ordinal on the relation. Without it the only way to know a junction's right
                # member would be to compare surfaces, which is string arithmetic inside the
                # ontology. It matters because a continuation attaches to the edge of the signal:
                # expanding a placed vertex through its colimit also puts its earlier members on
                # the screen, and drawing candidates from an earlier member's successors would
                # continue a position the text did not stop at.
                for at_m, (m, t_m) in enumerate(((a, ia), (b, ia + La))):
                    pr = {"bits_saved": saved, "at": at_m}
                    if (base_t + t_m) in step_e:
                        pr["energy"] = step_e[base_t + t_m]
                    edge(vid, _unit_id(collection, m), "observed", pr)

    # One transaction, not one write per unit. `put_artifact` runs on a connection opened with
    # `isolation_level=None` — autocommit — so writing the lexicon a row at a time would commit
    # once per unit. `put_many` batches inside a single BEGIN/COMMIT.
    docs = [{
        "id": _unit_id(collection, surf), "content_type": TOKEN_CT,
        "name": surf, "content": surf, "length": len(surf), "witnesses": int(c),
        "collection_id": collection, "collections": [collection],
        "created_by": "ember-source",
    } for surf, c in lex.items()]
    store.artifacts.put_many(docs + junctions + obs_rows)
    edges = [(s, d, l, pr) for (s, d, l), pr in _edge_props.items()]
    handled = store.graph.add_edges(edges)
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))

    # What is worth counting is how far the colimit has climbed: units covering more than one of
    # the text's runs are the phrases it built, and single-atom units are the words it was handed.
    # An atom keeps the space it closes, so a plain no-internal-space count would not distinguish
    # them.
    words = [u for u in lex if span.get(u, 1) > 1]
    say("delimit    %-10s %d chunk(s), mean %.1f unit(s) each"
        % (delimit, n_chunks, sum(lengths) / max(len(lengths), 1)))
    say("lexicon    %d unit(s) formed from EMPTY, longest %d atom(s)" % (len(lex), longest))
    say("fired      %d discharge(s), screen held %.1f step(s) at the gate (max %d)"
        % (fires, sum(widths) / max(len(widths), 1), max(widths or [0])))
    say("observations %d context vertex(es), each a colimit over its path" % len(obs_rows))
    say("neighbours %d distinct adjacency(ies) recorded" % len(neighbours))
    say("colimit    %d junction(s) inline" % len(junctions))
    say("admitted   %d unit(s) arrived unheld (%.0f%% of %d placement(s))"
        % (novel, 100.0 * novel / max(novel + N, 1), novel + N))
    say("phrases    %d unit(s) cover more than one run (%.0f%%)"
        % (len(words), 100.0 * len(words) / max(len(lex), 1)))
    say("edges      %d in %.1fs" % (len(edges), time.time() - t0))
    return {"chunks": n_chunks, "lexicon": len(lex), "junctions": len(junctions),
            "wordlike": len(words), "longest": longest, "edges": len(edges),
            "stream": stream}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("--text", required=True)
    ap.add_argument("--delimit", choices=("period", "line", "paragraph"), default="period")
    args = ap.parse_args()
    raw = open(args.text, encoding="utf-8", errors="replace").read()
    from mantle.shard.local_store import open_store
    read_stream(open_store(), args.collection, raw, delimit=args.delimit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
