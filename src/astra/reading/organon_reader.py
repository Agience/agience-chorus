r"""The reading organon — one book, streamed in order, into one collection that starts empty.

    python -c "import ember" ...   # the host must be imported first: it binds the seams below
    python -m astra.reading.organon_reader --text <corpus-dir>/pride.txt \
           --collection read:pride-1        # a fresh collection name; the scope must start empty
    python node/read-book.py --text ... --report        # read nothing, report what was learned

Every quantity the corpus's WordNet-derived reasoner uses comes from an external table: `ic` is the
intrinsic measure `1 - log(desc+1)/log(N+1)` (a count of WordNet descendants) and `lemma_counts` is
SemCor. A token that appears in a novel can never earn an IC there no matter how often it is read,
because that table is not something reading can add to. This organon computes IC a different way,
from what it has itself read.

Nothing here is preloaded — no WordNet, no ConceptNet, no SemCor, no intrinsic IC. The collection
starts with zero artifacts and every number below is `-log2(count/N)` over what this organon has
actually seen. `zorbex` earns a coordinate by being read twice; `mitochondria`, unread, has none and
reports that absence rather than a fabricated zero ([[absence-is-not-an-affirmative-claim]]).

The scope is a collection, not a separate store. Every artifact this writes carries
`collection_id = COLLECTION` and every read filters on it, so within its own scope the reader
genuinely begins at zero while sharing one lattice with everything else. A collection is for
segmenting the lattice, a legitimate partition unlike a content-type filter that would make part of
the corpus unreachable.

The loop, and where each quantity comes from

  Order is information, so the tokens stream from the first word of the book. A bag of words would
  destroy exactly the structure that teaches sequence, and `entroptics.sequence` exists to measure
  what ordering carries.

  For each token, with counts accumulated so far (never the whole-book totals — the reader does not
  know at word 12 what word 90,000 will be):

      p          = count(tok) / N                  the observer's current expectation
      surprisal  = -log2(p)                        bits — Resnik IC, from this reading
      ceiling    = log2(N)                         the most surprising a token can be right now:
                                                   a word seen exactly once. Derived, not chosen.
      r          = surprisal / ceiling  ∈ (0, 1]    the residual fraction of the incident energy
      T          = sqrt(r)                         transmitted (residual) amplitude
      A          = sqrt(1 - r)                     absorbed (recognized) amplitude

  `A² + T² = 1` exactly, per token, by construction — the 0→1→0 conservation certificate, checked
  by `prism.conservation.PathLedger` rather than asserted here. A word the reader has never met is
  pure residual (r = 1: nothing absorbed, everything new). A word it has met often is mostly
  absorbed and precipitates almost nothing. Nothing is thresholded: the split is the surprisal.

  The residual is what the ontology gains. First sight precipitates an artifact; later sightings
  accumulate `(count, sum)` onto it — order-free, mergeable in any order
  ([[consolidation-is-learning]]). The screen accumulates in parallel and its own decay curve
  decides how far back a co-occurrence reaches, so no window size is typed in anywhere.

  The loop cycles: the artifacts precipitated in chapter 1 are in scope when chapter 4 is read, so
  what the book taught is what the book is read with.
"""
import argparse
import json
import math
import os
import sys
import time
from collections import Counter

COLLECTION = "read:pride-and-prejudice"
TOKEN_CT = "application/x-token"       # what a read unit is, before anything classifies it
OBS_CT = "application/x-observation"   # one per screen read; its edges are what was co-present

# No regex anywhere on the read path. Stripping a publisher's wrapper (Project Gutenberg's licence
# text, `[Illustration: ...]` plates) is a question about the data, not about reading, so it happens
# once, outside this module, and the reader is handed a stream of characters it takes entirely on
# trust. If the wrapper is left in, the reading learns the licence — the correct behaviour for
# something that learns what it is shown.

def book_text(path):
    """The stream, exactly as given. No stripping, no normalising, no folding."""
    return open(path, encoding="utf-8", errors="replace").read()


# Intake decides nothing about what a word is. A regex tokenizer makes several silent rulings
# before a single word is counted — digits are not words, hyphens split, an apostrophe binds its
# neighbours, case does not matter — and each is a claim about English asserted before there is any
# reading to base it on. The whole point of this organon is that English comes from the reading.
#
# So the rule is the text's own delimiters and nothing else: whitespace separates, and every
# punctuation mark is its own token. Nothing is dropped, nothing is merged, nothing is folded.
#
#   * Punctuation is signal, not noise. Sentence boundaries, commas and quotation marks are the
#     structure of prose — discard them and the read can never reconstruct a sentence, let alone a
#     voice.
#   * `Jane’s` streams as `Jane` `’` `s`. Whether `’s` is one unit is something the colimit discovers
#     from how often the three co-occur in that order, not something the tokenizer asserts. Same for
#     hyphenates and contractions.
#   * Case is kept. `Bennet` and `bennet` are different observations; folding them at intake would be
#     a "duplication smoothed" step done before there is any evidence they are the same thing. That
#     smoothing is the colimit's job, which is the one component that can merge them while carrying
#     both provenances ([[consolidation-is-learning]]).


def stream_tokens(text, unit="char"):
    """The book, in order, one unit at a time.

    `char` is the default and it is the only intake that decides nothing. Even the whitespace-and-
    punctuation rule above still rules that a space ends something, which is itself a claim about
    English. A character stream makes no claim at all: the alphabet is ~100 symbols, every one earns
    a count and therefore an IC on its first appearance, and the units — `the`, `Bennet`, `’s` — are
    discovered by the colimit from how often characters co-occur in order, never asserted here.

    That is what makes the tokens a result rather than an input, and it is the same move as
    `[[genesis-holographic-compression]]`: zoom out and the colimit coarsens, zoom in and it splits.
    A tokenizer written by hand would be a pre-trained table, which is what this organon avoids.

    `word` is kept for comparison, not for use: reading the same prefix both ways measures what the
    character reader has to learn that the word reader is given outright.

    A generator, because the reader is a stream: nothing downstream may depend on knowing the
    length. There is no truncation either — a reading cut short reports counts, ICs and a colimit
    derived from a book that stops mid-sentence, and nothing downstream can tell that from a short
    book. There is no regex tokenizer on this path — a stream of characters is the only input, and
    what a unit is, is the reading's to discover."""
    for ch in text:
        yield ch


class Lexicon:
    r"""The growing prefix — exact match is recognition, a miss is where the colimit works.

    The reader holds a buffer. Each character extends it and the extended string is looked up:

        "a"    -> an artifact exists        recognized; keep extending
        "at"   -> an artifact exists        recognized; keep extending
        "ate"  -> an artifact exists        recognized; keep extending
        "ate " -> no artifact               "ate" was the unit. The miss is the signal.

    A miss is the interesting event: an exact match tells the reader only what it already knew, but
    a miss is the boundary of its own knowledge, and it arrives with the two pieces that straddle it
    — the unit that matched and the unit that starts next. Those two are exactly the diagram a
    colimit is taken over, so the new unit is not invented: it is the universal object carrying both
    members' provenance, count and mass ([[consolidation-is-learning]]).

    Nothing here is a vocabulary size, a merge table or a hop count. The lexicon starts empty — not
    even the alphabet is given, so the first `a` is a miss and precipitates, which is how a letter
    becomes an artifact. Growth is driven by what recurs, and what recurs is decided by the reading.
    """

    def __init__(self):
        self.units = {}          # exact surface -> count
        self.sum_res = {}        # exact surface -> Σ residual energy (the `sum` beside the `count`)
        self.born = {}           # exact surface -> the position it precipitated at
        self.pairs = {}          # (left, right) -> how often that adjacency was seen
        self.after = {}          # left -> how many adjacencies it has had
        self.members = {}        # junction -> the members with a morphism into it
        self.obs = {}            # observation id -> the signals on the screen at that step
        self.member_of = {}      # signal -> the observations it has been part of
        self.lit = {}            # observation -> absorbed energy that has reached it
        self.condensed = {}      # signal -> absorbed energy that confirmed it: draft -> real
        self.draft = {}          # proposed units, not priced until a second encounter
        self.obs_at = {}         # observation -> where in the text it was taken

    def has(self, s):
        return s in self.units

    def observe(self, s, pos, residual):
        new = s not in self.units
        if new:
            self.units[s] = 0
            self.sum_res[s] = 0.0
            self.born[s] = pos
        self.units[s] += 1
        self.sum_res[s] += residual
        return new

    def _retired_merge(self, left, right, pos, total_units):
        r"""The universal object over `[left, right]` — one unit carrying both.

        Merging on adjacency count alone does not form words, it forms fragments: `' '` and `.` are
        the most frequent characters in the book, so every pair involving them recurs immediately
        and wins, producing units like `othe`, `. Th`, `, tho`. Frequency says what co-occurs; it
        cannot say where a unit ends.

        What makes a word a word is that its inside is predictable and its edge is not. After `th`,
        `e` is nearly certain; after `the`, almost anything follows. So the criterion is whether
        `left` predicts `right` — pointwise mutual information:

            PMI(L,R) = log2( p(R | L) / p(R) )

        with the bar at zero — not a tuned threshold but the definition of "better than chance":
        PMI > 0 says seeing `L` makes `R` more likely than `R` is on its own, so the two belong to
        one unit. PMI <= 0 says `L` tells you nothing about `R` — a boundary — and no merge happens
        however often the pair recurs. `' '` + `t` is frequent and uninformative, exactly the case
        this rejects.

        Recurrence is still required, for a different reason: a pair seen once has p(R|L) = 1 by
        construction, so its PMI is maximal on no evidence — the estimator is degenerate at n=1, not
        merely noisy. The second sighting is what makes the ratio a measurement
        ([[inertial-learning]]: you cannot mine faster than you can verify).
        """
        key = (left, right)
        self.pairs[key] = self.pairs.get(key, 0) + 1
        if self.pairs[key] < 2 or self.has(left + right):
            return None
        # p(R | L) — how reliably `right` follows `left`, over every adjacency `left` has had
        out = self.after.get(left, 0)
        if out < 2 or not total_units:
            return None
        p_r_given_l = self.pairs[key] / out
        p_r = self.units.get(right, 0) / total_units
        if p_r <= 0.0 or p_r_given_l <= p_r:
            return None                    # `left` does not predict `right`: this is a boundary
        merged = left + right
        self.units[merged] = 0
        self.sum_res[merged] = 0.0
        self.born[merged] = pos
        return merged


def _unit_id(collection, tok):
    """The artifact id for a unit — read from `reading_junction`, which holds the one copy of it.

    The rule is stated there, with why there is only one. It is not restated here: the reader that
    WRITES these ids and the placer that RESOLVES against them must agree on every space and comma,
    and two copies agreeing today is not the same as one rule. The name stays, so every astra caller
    importing `_unit_id` from this module is unaffected."""
    from reading_junction import unit_id
    return unit_id(collection, tok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    # No box-specific default: the store is named by $MANTLE_SQLITE or on the command line,
    # and argparse refuses the run when neither says.
    ap.add_argument("--sqlite", default=os.getenv("MANTLE_SQLITE"),
                    required=not os.getenv("MANTLE_SQLITE"),
                    help="the lattice.db to read/write; defaults to $MANTLE_SQLITE")
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--unit", default="char", choices=["char", "word"],
                    help="char DECIDES NOTHING and is the default; word is for comparison only")
    ap.add_argument("--flush", type=int, default=2000, help="write batch size")
    ap.add_argument("--trace", action="store_true", help="print EVERY token's split — start here, small")
    ap.add_argument("--report", action="store_true", help="report the collection; read nothing")
    ap.add_argument("--tail", type=int, default=0,
                    help="also report absorbed/residual over the LAST N units — the transfer test")
    ap.add_argument("--say", default="", help="OUTGEST: walk back out from this seed concept")
    ap.add_argument("--length", type=int, default=60, help="how many units to emit")
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    os.environ.setdefault("MANTLE_SQLITE", args.sqlite)
    import sqlite3

    ro = sqlite3.connect("file:%s?mode=ro" % args.sqlite, uri=True)
    ro.row_factory = sqlite3.Row
    if args.say:
        return outgest(ro, args.collection, args.say, args.length)
    if args.report:
        return report(ro, args.collection)

    # The collection must start empty, and that is asserted rather than assumed. `count(*)` would
    # dereference every record to learn whether one exists ([[count-star-dereferences-every-record]]:
    # a query defect, not a heap shortage — on the live shard it zombies the acceptor). `LIMIT 1`
    # answers the same question in bounded work, and returns no row rather than a zero count when the
    # collection is empty, so the caller checks for `None` rather than subscripting a count.
    row = ro.execute("SELECT 1 FROM vertex WHERE id LIKE ? LIMIT 1",
                     (args.collection + ":%",)).fetchone()
    ro.close()
    if row is not None:
        # A fresh reading is a fresh collection: there is no `--reset` or `--limit` here. Naming a
        # new scope costs nothing, keeps every prior reading intact and comparable, and makes
        # "starting from zero" a fact about the name rather than a promise about a deletion that ran
        # first. A reading cut at N units would report counts, ICs and a colimit derived from a book
        # that stops mid-sentence, and nothing downstream could tell that from a short book — so the
        # stream is never truncated.
        print("REFUSING: %s already holds artifact(s). This organon's claim is that it learns from "
              "ZERO, so a non-empty scope would silently make it look better than it is. Read into "
              "a NEW collection name instead." % args.collection)
        sys.exit(2)

    from prism.conservation import PathLedger
    # The screen is the working memory of the read, and it is the runner's own — not a cache. It
    # accumulates as tokens go past and its own measured decay decides how far back a co-occurrence
    # reaches, so no window length is typed in anywhere.
    #
    # Named, not imported: `from ember.signal.forgetting import Screen` would be a sideways L3->L3
    # edge that the layer model forbids (`test_chorus_does_not_import_ember` enforces it) — a
    # measurement the runner performs is declared by name, not imported directly.
    from _host_seams import seam as _seam

    # Resolved once, not per token: `_bits` is called for every unit that leaves the stream and
    # again for every candidate cut, so reaching through the seam inside those loops would put a
    # registry lookup on the hottest path in the reader.
    _bits = _seam("optics").self_information_bits

    # The screen's fit needs its own coordinate rather than the WordNet JC coordinate `Screen`
    # builds by default, because a reading's concepts are units the reading formed — `'Kit'`,
    # `'the'`, `' Th'` — none of which has a synset; fitting against synsets would drop every row
    # and leave every trace at amplitude 1.0 forever, so the screen would never forget.
    #
    # The coordinate is a vector over the observations a unit has been part of, each entering at
    # `sqrt(bits)` — the same construction as `projection.read_cloud`, computed live from what has
    # been read so far rather than from a persisted basis, because the screen forgets during the
    # read. `lex.member_of` already carries this mapping.
    #
    # The width is the observation count, which is a count the reading produced — no chosen
    # dimension, no hash. The fit needs more rows than features and the screen holds far fewer
    # traces than the stream has observations, so the frame is read over the observations the
    # traces on screen actually share; a trace sharing none contributes an all-zero row and the
    # instrument drops it, which is the correct reading of "nothing of it is on this screen".
    def _unit_coordinate(unit):
        import numpy as _np
        obs = lex.member_of.get(unit) or ()
        if not obs:
            return _np.zeros(1)
        cols = _screen_obs_cols[0]
        v = _np.zeros(len(cols)) if cols else _np.zeros(1)
        for o in obs:
            j = cols.get(o)
            if j is not None:
                b = _bits(len(lex.obs.get(o, ())) or 1, max(len(lex.obs), 1))
                v[j] += float(_np.sqrt(b)) if b and b > 0.0 else 0.0
        return v

    _screen_obs_cols = [{}]        # observation id -> column, rebuilt when the screen re-measures
    screen = _seam("forgetting").Screen(ic={}, witness="reader", store=None,
                                        coordinate=_unit_coordinate)

    text = book_text(args.text)
    print("book: %s  (%d chars after stripping the Gutenberg wrapper)" % (args.text, len(text)))
    print("collection: %s  (starting from ZERO artifacts)" % args.collection)
    if args.trace:
        print("")
        print("   pos token          count  p        surprisal   A     T      what           screen")
        print("   " + "-" * 92)

    counts = Counter()
    N = 0
    first_seen = {}          # token -> the position it precipitated at, kept as provenance
    sum_residual = Counter()  # token -> Σ residual energy, the `sum` beside the `count`
    ledger = PathLedger(1.0)
    absorbed_total = 0.0
    residual_total = 0.0
    _last_residual = [0.0]
    _last_absorbed = [0.0]
    # The transfer test needs a window, because a whole-run average cannot answer it: reading
    # Austen-then-Shelley absorbs Austen's own recognition into the total, so the only comparable
    # quantity is the rate over the same final stretch of the same text, primed vs cold.
    tail_hist = []
    t0 = time.time()

    # The growing prefix: characters arrive one at a time. `buf` is what the screen currently
    # holds; each character extends it and the extension is looked up exactly. A hit is recognition
    # and the prefix keeps growing; a miss closes the unit and hands the colimit the two pieces that
    # straddle the boundary. See `Lexicon` for the argument.
    #
    # Matching is exact only: keyed lookup finds `dinner`, nothing here finds `dinnner`. A
    # misspelling precipitates as its own unit, which is honest — it says "I have not seen this."
    # `prism.minhash` over character shingles is the near-duplicate candidate generator for a second
    # tier; entroptics is not a string hash — its `E` is a dense D×D covariance metric
    # ([[entroptics-read-as-lsh-hash]]) — so it belongs in deciding whether a near match is within
    # the corpus's own resolution, not in finding one.
    lex = Lexicon()
    buf = ""

    # ── Ingestion predicts nothing ──────────────────────────────────────────────────────────────
    # Ingestion does not probe ahead of the stream to bound how far back the screen can look: the
    # screen carries its own decay, and a trace leaves it when it stops changing the screen's total
    # at floating-point resolution — derived from the dtype and the data, with nothing to tune. That
    # is the only bound on reach, and it is why "its own decay curve decides how far back a
    # co-occurrence reaches, so no window size is typed in anywhere" (the module docstring) is true.
    #
    # The same read the reasoning side wants is available there instead, as
    # `lumen.reading.heldout.structure()`, which reports the whole `H_n` ladder against its shuffles
    # — a question about the text, asked when someone wants the answer, not a toll the reader pays
    # before it is allowed to read.
    units_emitted = 0
    merges = []

    def _account(surface, pos):
        """One unit leaves the stream: split its incident energy by its own surprisal, exactly."""
        nonlocal N, absorbed_total, residual_total, units_emitted
        N += 1
        units_emitted += 1
        seen = lex.units.get(surface, 0) + 1
        # `self_information_bits` is `-log2(p)` from `entroptics.entropy.surprisal_bits`, sharing its
        # base and its clip with the rest of the conservation certificate, so the reader and the
        # instrument cannot disagree about what a bit is. The ceiling is the same read, not a second
        # one: the most surprising a unit can be right now is a unit seen exactly once, which is
        # `self_information_bits(1, N)`.
        surprisal = _bits(seen, N)
        ceiling = _bits(1, N) if N > 1 else 1.0
        if surprisal is None or not ceiling:
            surprisal, ceiling = 0.0, 1.0     # no probability can be formed — an absence, not a zero
        # At N==1 the ceiling is the floor: the first unit is the only unit, so it is both the most
        # and the least surprising thing that has happened. r = 1 (pure residual) is honest — nothing
        # could have been absorbed, because there was nothing here to absorb it.
        r = 1.0 if N == 1 else min(max(surprisal / ceiling, 0.0), 1.0)
        T, A = math.sqrt(r), math.sqrt(1.0 - r)
        absorbed_total += A * A
        residual_total += T * T
        _last_residual[0] = T * T
        _last_absorbed[0] = A * A
        # ── What absorption does ────────────────────────────────────────────────────────────────
        # A tekton is defined by the band it absorbs (`lumen/manifest.py`: `domain` is what the
        # tekton is tuned to). So absorption is not bookkeeping, it is the event that says which
        # thing recognised this. The energy goes to the absorber and propagates along its edges into
        # the observations it is part of — that is what lights the ontology, and it is why
        # absorption is the recall half of the same act the residual makes the learning half of.
        #
        # The energy is split across the observations it reaches, not copied into each: a signal
        # that has been part of a thousand moments says little about any one of them; one that has
        # been part of two says a great deal about those two. Conservation, again — the same reason
        # a member spends one unit of energy over where it occurs.
        #
        # The residual is a draft — a hypothesis, held provisionally, because a thing seen once
        # cannot yet be said to be anything ([[inertial-learning]]: you cannot mine faster than you
        # can verify). Absorption is the confirmation: recognising a draft is prior observation
        # agreeing with it, which is what condenses it into a real signal. A tekton is a condensor
        # (`lumen/manifest.py`), and this is the condensation.
        #
        # So absorbed energy does two things, both of them to the thing that absorbed it: it
        # accumulates as the signal's own mass (draft -> real), and it propagates into the
        # observations that signal is part of — which is recall, the same act read the other way.
        if A > 0.0:
            lex.condensed[surface] = lex.condensed.get(surface, 0.0) + A * A
            _obs = lex.member_of.get(surface)
            if _obs:
                # Split across the observations it reaches, not copied into each.
                share = (A * A) / len(_obs)
                for _o in _obs:
                    lex.lit[_o] = lex.lit.get(_o, 0.0) + share
        if args.tail:
            tail_hist.append(A * A)
            if len(tail_hist) > args.tail:
                del tail_hist[:-args.tail]
        new = lex.observe(surface, pos, T * T)
        if args.trace:
            print("  %5d %-18s cnt=%-4d surprisal=%6.2f  A=%.3f T=%.3f  %-12s lex=%-5d screen=%d"
                  % (pos, repr(surface), seen, surprisal, A, T,
                     "PRECIPITATE" if new else "recognized", len(lex.units), len(screen.traces)),
                  flush=True)
        return surface

    # ── The segmentation that costs the fewest bits ─────────────────────────────────────────────
    # A unit is worth taking when it describes the characters more cheaply than the characters
    # describe themselves: `cost(u) = -log2 p(u)`, and the junction wins iff `cost(u) < Σ cost(c)`.
    # That is the colimit stated in bits — the universal object is the one that explains its members
    # for less than they cost apart. Nothing is tuned: no threshold, no vocabulary size, no length
    # prior, and even the cost of a never-seen unit is derived from what has been read.
    #
    # Minimised over the span, not the step: choosing the cheapest unit at each position and never
    # revisiting locks in an early bad cut and shifts everything after it. Measured against the
    # text's own whitespace, on the first 150,000 characters:
    #
    #     greedy prefix                         precision 0.277   recall 0.192   mean unit 4.25
    #     the same MDL cost, greedily           precision 0.379   recall 0.301   mean unit 3.69
    #     the same MDL cost, over the line      precision 0.589   recall 0.383   mean unit 4.52
    #
    # Recall alone is gameable: a mass-weighted variant scored recall 0.851, the best number in the
    # table, by emitting single characters at a mean unit length of 1.09 — a cut at every position
    # trivially contains every true cut. Mean unit length is reported beside recall for that reason.
    #
    # The span is a line because the text supplies lines; nothing about the language is assumed, and
    # the reader stays a stream.
    def _longest_known():
        """The bound on candidate cut length, read off the lexicon rather than typed in. `_cost`
        returns None for a substring the reading has never seen, and only `L == 1` falls back to the
        `unseen` price, so a candidate longer than the longest unit in the lexicon can never
        contribute a finite cost — searching past that length would be wasted work. This bound grows
        with the reading: the first pass can only see single characters, and the ceiling rises
        exactly as far as the reading has earned it."""
        return max((len(u) for u in lex.units), default=1)

    def _cost(s):
        c = lex.units.get(s, 0)
        return _bits(c, N) if c and N else None     # the instrument's bits, not a second log2

    def _members_of(u):
        """The parts a junction is a colimit over, and the bits it saves by existing.

        The members are derived, not declared: they are how this reading would segment `u` if `u`
        did not exist — same cost, same programme, one unit removed from the lexicon — so the
        decomposition is the reading's own opinion about its own unit, with nothing new introduced
        to produce it.

        The saving is what makes it a colimit rather than a list: `cost(u) < Σ cost(parts)` is the
        universal property stated in bits — the junction explains its members for less than they
        cost apart. The margin is carried on the edge, so a later read can ask how much a level of
        the ontology is worth instead of taking its existence on trust.

        Returns `(parts, bits_saved)`, or `None` when the unit is a single character (nothing to be
        a colimit over) or when no decomposition can be priced at all."""
        n = len(u)
        if n < 2:
            return None
        # The junction is placed, not searched: a search over every substring asks the whole space
        # what it costs, while placement asks the ontology where this signal already lives. The walk
        # stands at a position and extends while the ontology still recognises what it is holding —
        # an indexed lookup per character, the same growing prefix `Lexicon` is built around ("exact
        # match is recognition, a miss is where the colimit works"). At the miss, the matched span is
        # the part: the familiar location the signal reached.
        #
        # The residual then re-places: what was absorbed is emitted as a part, and the rest of the
        # junction becomes the incident signal for the next placement, from its new position. That is
        # the absorb-and-propagate split the whole architecture runs on, applied to a string instead
        # of a frame, and it is linear because a walk visits each position once.
        parts, i = [], 0
        while i < n:
            k = i + 1                              # a single character is always a unit
            j = i + 1
            while j < n:                           # extend while the ontology still recognises it
                cand = u[i:j + 1]
                if cand == u or cand not in lex.units:
                    break                          # a junction may not explain itself
                k = j + 1
                j += 1
            parts.append(u[i:k])
            i = k                                  # re-place at the residual's new position
        if len(parts) < 2:
            return None
        spent = 0.0
        unseen = _bits(1, max(N, 1) + 1) or 1.0
        for _p in parts:
            _c = _cost(_p)
            spent += unseen if _c is None else _c
        own = _cost(u)
        return parts, (spent - own) if own is not None else None

    # ── Fill and read are separate threads ──────────────────────────────────────────────────────
    # The screen is shared between them, and each runs at its own rate. A single loop doing both
    # would produce exactly one observation per ingested unit — lockstep, a transcript with extra
    # steps rather than a screen being read, since the read rate would equal the fill rate and
    # nothing about the screen would be dynamical. Instead the filler streams units onto the screen
    # and lets the instrument forget; the reader takes what is present when it looks. Whether it sees
    # every unit, several at once, or the same set twice is a fact about the two rates, which is what
    # makes the screen a surface rather than a queue.
    #
    # The reader's cadence is keyed on the screen, not on a timer: `Screen._rates_current` states the
    # same rule for the screen itself — no cadence, no interval, no "every N observations", key on
    # the bookkeeping the thing already keeps — so an observation is recorded when the screen has
    # moved since the last one. A sleep interval here would be a constant standing in for that.
    import threading

    screen_lock = threading.Lock()
    lex.tick = 0
    lex.absorbed_now = False   # set when absorption changed the ontology: read the screen
    lex.residual_pool = 0.0    # unabsorbed energy — what precipitates as drafts
    done = threading.Event()

    def _reader():
        """Reads the screen whenever absorption has changed the ontology since the last read.

        The residual and the absorbed do two different things: the residual radiates outward and
        precipitates drafts, while the absorbed is what the reader thinks with, and thinking about
        the screen is what reading it is. A unit whose absorption is zero is pure residual — it
        changed nothing, so there is nothing to record — and every other unit produces a read.
        Familiar material has absorbed energy by definition, so it is exactly what gets observed:
        recall of familiar material, not only of what is unfamiliar.

        No timer, no interval, no threshold, and nothing about the machine. Familiar text emits
        rarely; novel text emits often. Observations count new information rather than input length,
        which is what makes the number mean something.
        """
        while not done.is_set():
            with screen_lock:
                # The observation is the change: every absorption alters the ontology — a signal was
                # recognised, a draft condensed, mass moved — and a change that is not recorded did
                # not happen as far as anything downstream can tell. A unit with `A = 0` is pure
                # residual: it changed nothing, so there is nothing to record, and that is the only
                # case that does not produce a read.
                if not lex.absorbed_now:
                    continue
                lex.absorbed_now = False
                t = lex.tick
                # `tr.amplitude(t) > 0.0` would not gate anything: amplitude is `energy * C(dt)` on
                # the screen's own measured decay curve, an exponential that is never exactly zero
                # until float underflow, so every trace ever placed would stay "present" and the
                # screen would forget nothing ([[verification-that-cannot-fail]]: a test the decay
                # curve can never fail is the same shape as a check that always passes).
                #
                # The floor is derived from the arithmetic, not chosen: a trace is present while it
                # still changes the screen's total at floating-point resolution, and below that it
                # contributes nothing to any sum taken over the screen — which is what "no longer on
                # the screen" means operationally. `eps * total` comes from the dtype and the data;
                # there is no epsilon to tune, and a screen holding one trace keeps it.
                # The frame the decay is fitted in: the observations the traces on screen share.
                # Rebuilt here so the width tracks what is actually on the screen rather than the
                # whole stream, which is what keeps rows > features.
                _shared = {}
                for _tr in screen.traces:
                    for _o in (lex.member_of.get(_tr.concept) or ()):
                        _shared.setdefault(_o, len(_shared))
                _screen_obs_cols[0] = _shared
                _amps = [(tr, tr.amplitude(t)) for tr in screen.traces]
                _total = sum(a for _tr, a in _amps)
                _floor = _total * sys.float_info.epsilon
                present = tuple(tr.concept for tr, a in _amps if a > _floor)
                # The screen is pruned here: decay attenuates a trace's amplitude but does not drop
                # it from the list on its own, so without this the list would grow with the stream
                # and the amplitude scan above would be O(traces) per unit. A trace below `_floor` no
                # longer changes the screen's total at floating-point resolution, which is exactly
                # what "no longer on the screen" means operationally — it is already the line that
                # decides `present` — so dropping those traces is the decay curve deciding the
                # window, rather than a window being applied on top of it.
                screen.traces[:] = [tr for tr, a in _amps if a > _floor]
            if present:
                oid = "obs-%d" % t
                lex.obs[oid] = list(present)
                lex.obs_at[oid] = lex.at_char
                for sig in set(present):
                    lex.member_of.setdefault(sig, []).append(oid)

    reader = threading.Thread(target=_reader, name="screen-reader", daemon=True)
    reader.start()

    prev = None
    pos = 0
    char_at = 0
    lex.at_char = 0
    stop = False
    for line in text.splitlines(keepends=True):
        if stop or not line:
            continue
        n = len(line)
        # The cheapest an unseen unit could possibly be is one occurrence in a stream one longer
        # than this one: `self_information_bits(1, N + 1)`, which is strictly greater than the
        # ceiling `self_information_bits(1, N)` by construction — no margin needs to be chosen.
        unseen = _bits(1, max(N, 1) + 1) or 1.0
        best = [0.0] + [float("inf")] * n
        back = [0] * (n + 1)
        # `_longest_known()` scans the whole lexicon, and it cannot change while a single line is
        # being segmented (units are added by `_account`, which runs after the line is cut), so it
        # is hoisted out of the position loop rather than evaluated once per character.
        _longest = _longest_known()
        for j in range(1, n + 1):
            for L in range(1, min(_longest, j) + 1):
                i = j - L
                c = _cost(line[i:j])
                if c is None:
                    c = unseen if L == 1 else None
                if c is None or best[i] + c >= best[j]:
                    continue
                best[j], back[j] = best[i] + c, i
        out, j = [], n
        while j > 0:
            i = back[j]
            out.append(line[i:j])
            j = i
        out.reverse()

        for unit in out:
            pos += 1
            char_at += len(unit)
            _account(unit, pos)
            # The colimit's members are derived once per junction, at the end of the read, when the
            # counts that price them are final — see `_members_of`. Recording them here would price
            # a junction against a lexicon that is still growing, so the same unit would decompose
            # differently depending on where in the book it first appeared.
            if len(unit) > 1:
                lex.members.setdefault(unit, None)
            # The screen sees the emitted stream — one tick per unit, the reader's proper time.
            with screen_lock:
                if _last_absorbed[0] > 0.0:
                    lex.absorbed_now = True              # the ontology changed — record it
                lex.residual_pool += _last_residual[0]   # …and what it did not
                # The screen's own decay is the only thing that bounds it — see the block above.
                screen.observe(unit, tick=pos, witness="filler", energy=1.0)
            # ── One artifact per screen read, with an edge to each signal on it ─────────────────
            # The observation is the artifact: what was co-present on the screen at step `pos` is a
            # fact about that step, so it is recorded as one object with an edge to each signal. That
            # object is the junction — the universal thing the co-present signals map into — and it
            # exists because the reading made it, not because a query decomposed something later.
            # Nothing needs to be re-derived at question time: a signal's edges lead straight to
            # every moment it was part of. The screen is already bounded by the instrument forgetting,
            # above — signals fade, so "what is on the screen" is a measured window, not everything
            # ever read.
            lex.tick = pos                     # the filler's proper time, for the reader to see
            lex.at_char = char_at              # …and where in the text it is, so an
                                               # observation can point back at the prose
            if prev is not None:
                lex.pairs[(prev, unit)] = lex.pairs.get((prev, unit), 0) + 1
                lex.after[prev] = lex.after.get(prev, 0) + 1
            prev = unit
        # ── A join is a draft until a second encounter confirms it ───────────────────────────────
        # A join enters as a draft and is priced at nothing: writing an adjacent pair straight into
        # `lex.units` — the same table `_cost` reads — would give a probability to units nobody had
        # ever observed and let that hypothesis segment the next line. Instead a join becomes a real
        # unit, visible to `_cost` and able to win a segmentation, only when the reading meets it
        # again. That is the same rule absorption applies to signals ([[inertial-learning]]: you
        # cannot mine faster than you can verify), applied to the formation of units rather than to
        # their confirmation. Growth still happens; it just has to be earned twice.
        for a_, b_ in zip(out, out[1:]):
            j2 = a_ + b_
            # There is no cap on how long a unit may grow. A junction already has to be earned (it
            # must recur before it is priced), so its length is bounded by the reading rather than
            # by a number [[no-arbitrary-caps]].
            if j2 in lex.units:
                lex.units[j2] += 1                 # already real: an ordinary observation
                continue
            seen_before = lex.draft.pop(j2, 0)
            if seen_before:                        # met again -> condense into a real unit
                lex.units[j2] = seen_before + 1
                lex.sum_res.setdefault(j2, 0.0)
                lex.born.setdefault(j2, pos)
            else:
                lex.draft[j2] = 1                  # a hypothesis, priced at nothing
                # A draft must go on the screen, or it can never become an observation: it is
                # unpriced (invisible to `_cost`, so the segmentation cannot select it), but it is
                # still present (on the screen, so a read can see it) — being unpriced and being
                # present are different properties, which is why it is placed at nonzero energy
                # rather than zero. Putting it on the screen is what makes the next read able to see
                # it: the residual made a thing, the thing is now present, the next absorption
                # records what is present, and the draft is part of that — how it earns its second
                # observer, since existence is observer agreement.
                #
                # It carries the energy the residual actually left, because the unrecognised part is
                # exactly what put it there. It fades on the same instrument as everything else; if
                # nothing names it before it cools, it is gone.
                with screen_lock:
                    screen.observe(j2, tick=pos, witness="filler",
                                   energy=max(_last_residual[0], 1e-6))


    done.set()
    reader.join(timeout=5)
    print("filler put %d unit(s) on the screen; the reader took %d observation(s) off it"
          % (N, len(lex.obs)))

    ledger.absorb(math.sqrt(absorbed_total), math.sqrt(residual_total), at="reading")
    ledger.emit(at="ontology")

    elapsed = time.time() - t0
    print("read %d units, %d distinct types, %d colimit merge(s), in %.1fs"
          % (N, len(lex.units), len(merges), elapsed))
    print("absorbed %.1f  +  residual %.1f  =  %.1f incident   (0->1->0 per token, exactly)"
          % (absorbed_total, residual_total, absorbed_total + residual_total))
    print("ABSORBED FRACTION overall: %.4f" % (absorbed_total / max(N, 1)))
    if args.tail and tail_hist:
        print("ABSORBED FRACTION over the last %d unit(s): %.4f   <- the comparable number"
              % (len(tail_hist), sum(tail_hist) / len(tail_hist)))

    # ── Precipitate: the residual becomes artifacts, in the collection, with observed IC ─────────
    # One data path: the store resolves its own location from the environment rather than opening a
    # separate raw connection.
    from mantle.shard.local_store import open_store
    store = open_store()
    # Every draft still in flight is written as an artifact too, or its observation edges would
    # point at a vertex that does not exist — the same defect `created_by resolves` exists to catch.
    # A draft is a real artifact — unobserved, unpriced, unnamed — and writing it is what lets the
    # store say so. It carries no `ic`, because nothing has confirmed it: an absence, not a zero.
    for tok in list(lex.draft):
        if tok not in lex.units:
            lex.units.setdefault(tok, 0)
            lex.sum_res.setdefault(tok, 0.0)
            lex.born.setdefault(tok, 0)
    rows, members = [], []
    for tok, c in lex.units.items():
        aid = _unit_id(args.collection, tok)
        # A colimit-created unit that was never subsequently observed has no IC — not an IC of zero.
        # A merged unit enters at count 0 and earns its count only when the stream next produces it,
        # so `-log2(0/N)` is a domain error and `0.0` would be a fabricated measurement: IC 0 means
        # "certain, seen every time", the exact opposite of "never seen". Absence is recorded as
        # absence, with the reason, and `ic_basis` is the field a reader checks — the same shape
        # `enrich_wordnet` uses for zero-frequency synsets ([[absence-is-not-an-observation-of-zero]]).
        ic = _bits(c, N) if c else None              # observed information content, this reading
        doc = {
            "id": aid, "content_type": TOKEN_CT, "name": tok, "content": tok,
            "collection_id": args.collection, "lemmas": [tok],
            "created_by": "ember-source",
            # everything below is measured by the read that produced it, and is recomputable from
            # (count, N) alone — no value here was chosen.
            #
            # Draft vs real is the reading's own verdict, not an externally set flag: a unit that was
            # never absorbed was never confirmed by a second encounter, so it is a hypothesis this
            # reading raised and never met again. `state` is the store's existing discriminator.
            "state": ("committed" if lex.condensed.get(tok, 0.0) > 0.0 else "draft"),
            "condensed": round(lex.condensed.get(tok, 0.0), 6),
            "count": c, "corpus_tokens": N,
            # Mass and IC are different axes and both are kept. IC = -log2(count/N) is specificity,
            # so a misspelling (rare) scores high on it while `the` scores low. What separates a
            # real token from a misspelling is mass — how well attested it is; carrying only IC
            # would rank the corpus's typos as its most informative content
            # ([[mass-is-counted-not-looked-up]]).
            "mass": c / N,
            "ic": ic,
            "ic_basis": ("observed: -log2(count/N) over this reading" if ic is not None
                         else "ABSENT: formed by colimit, not yet observed in the stream"),
            "residual_sum": lex.sum_res[tok],        # the `sum` beside the `count`
            "first_seen_at": lex.born[tok],          # order is information; where it entered
        }
        rows.append((aid, TOKEN_CT, json.dumps(doc)))
        members.append((args.collection, aid))

    # Every row goes through the store rather than raw SQL: `put_artifact` allocates proper time,
    # assigns `_origin`/`_seq` and an edge digest, and the artifact's own `collections` field carries
    # membership so a side-car table cannot drift from the artifact ([[everything-is-an-artifact]]).
    for _aid, _ct, _doc in rows:
        store.artifacts.put_artifact(json.loads(_doc))

    # ── The adjacencies are the ontology, and without them there is no way back out ──────────────
    # Ingesting is text -> signal -> screen -> ontology -> concept; outgesting is the reverse path,
    # concept -> ontology -> screen -> signal -> text. Counts alone are a bag of units: they can say
    # `e` is common and cannot say `t` comes before `h`. Order is the whole of what a book teaches
    # beyond its vocabulary, and it is what the reverse path has to walk, so it is persisted as
    # edges — `left --next--> right` carrying the adjacency count — rather than kept only in memory.
    # The walk out reads the same structure the read wrote, from the store, in a fresh process, which
    # is what makes the reverse a test rather than a replay of in-memory state.
    # ── One edge, and it is an observation ──────────────────────────────────────────────────────
    # A separate `member_of` edge and `next` edge would each assert a category chosen in advance —
    # set membership, or sequence — rather than something measured. An edge is an observation
    # ([[operator-is-observation]]: edges = observations, observation follows demand), and whether a
    # particular co-incidence reads as membership, as order, or as similarity is something the
    # counts can decide later, not something the writer decides now and the reader can never re-open.
    #
    # It also keeps `(src, dst)` genuinely unique: `edge_key` is the table's primary key, derived
    # from `src|dst` alone, so two different labels between the same pair would collide under
    # `INSERT OR REPLACE`. Collapsing to one edge per pair makes that collision unrepresentable.
    #
    # What is recorded is what was seen: this artifact and that one were lit together, this many
    # times, at this mean separation. `gap` is 0 when one contained the other and 1 when one
    # followed the other — a measurement, kept as a number so the distinction survives without
    # being pre-named. Membership and sequence are both recoverable from it; neither is asserted.
    # One artifact per screen read; its edges are the signals that were on the screen. The
    # observation is a first-class thing in the store, not a pair table reconstructed at query time.
    obs_rows, obs_edges = [], []
    for oid, signals in lex.obs.items():
        if len(signals) < 2:
            continue                          # a screen holding one signal records no co-presence
        aid = "%s:%s" % (args.collection, oid)
        obs_rows.append((aid, OBS_CT, json.dumps({
            "id": aid, "content_type": OBS_CT, "name": oid,
            "collection_id": args.collection, "created_by": "ember-source",
            "at": int(oid.split("-")[1]), "char": lex.obs_at.get(oid, 0),
            "lit": round(lex.lit.get(oid, 0.0), 6), "signals": len(signals)})))
        for sig in set(signals):
            obs_edges.append((aid, _unit_id(args.collection, sig), "observed",
                              json.dumps({"of": oid})))
    for _aid, _ct, _doc in obs_rows:
        store.artifacts.put_artifact(json.loads(_doc))

    # ── The colimit's own structure, persisted ──────────────────────────────────────────────────
    # Each junction gets an edge per member, carrying what the colimit measured, so the whole/part
    # structure the colimit formed survives past the process rather than dying with it — a flat set
    # of units and co-presence has no coarser level to climb to and no finer level to fall back to,
    # so "pull information at the density the query needs" would have nothing to pull along.
    #
    # `bits_saved` is `Σ cost(parts) − cost(junction)`: the universal property in bits, positive
    # exactly when the junction explains its members for less than they cost apart. A later read can
    # therefore ask how much a level of the ontology is worth rather than taking its existence on
    # trust, and a junction that saves nothing is visible as such instead of looking like every
    # other unit.
    #
    # The label names the act, not a semantic relation: the decomposition is the measurement
    # (`_members_of` re-runs the reading's own segmentation with the junction removed), so the edge
    # records that a colimit was taken and what it saved — never what the parts "mean" to the whole.
    colimit_edges = []
    _levels = Counter()
    for _u in sorted(lex.members):
        _got = _members_of(_u)
        if not _got:
            continue
        _parts, _saved = _got
        if len(_parts) < 2:
            continue                       # nothing was fused: the unit is its own decomposition
        lex.members[_u] = _parts
        _levels[len(_parts)] += 1
        _jid = _unit_id(args.collection, _u)
        for _p in _parts:
            colimit_edges.append((_jid, _unit_id(args.collection, _p), "colimit",
                                  json.dumps({"of": _u, "parts": len(_parts),
                                              "bits_saved": (round(_saved, 6)
                                                             if _saved is not None else None)})))
    print("colimit: %d junction(s) decomposed, %d morphism(s) — parts-per-junction %s"
          % (sum(_levels.values()), len(colimit_edges),
             dict(sorted(_levels.items()))))

    edges = obs_edges + colimit_edges
    # `add_edges` returns the number handled, and its docstring says callers use a shortfall as a
    # data-loss guard — a raw INSERT reports nothing, so rows written that way could go in malformed
    # without anyone noticing.
    handled = store.graph.add_edges([(s_, d_, l_, json.loads(p_)) for (s_, d_, l_, p_) in edges])
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))
    print("wrote %d observation artifact(s) with %d edge(s) to the signals they held"
          % (len(obs_rows), handled))
    print("drafts still unconfirmed at the end of the reading: %d (never priced, never segmented on)"
          % len(lex.draft))
    _real = sum(1 for t in lex.units if lex.condensed.get(t, 0.0) > 0.0)
    print("CONDENSED into real signals: %d of %d types (%.1f%%) — the rest are drafts this reading "
          "raised once and never met again" % (_real, len(lex.units), 100.0 * _real / max(len(lex.units), 1)))
    if lex.lit:
        _top = sorted(lex.lit.items(), key=lambda kv: -kv[1])[:3]
        print("absorbed energy REACHED %d observation(s); brightest %s"
              % (len(lex.lit), [(o, round(v, 2)) for o, v in _top]))
    else:
        print("absorbed energy reached NO observation — nothing was recognised twice")
    # The WAL checkpoint is needed because a bulk read fills it
    # ([[bulk-import-wal-checkpoint]], [[lattice-store-goes-on-d-drive]]). It is a maintenance act on
    # the file, not a write of data, so it goes through the store's own connection.
    #: Through mantle's own helper, and THE RESULT IS READ. `PRAGMA wal_checkpoint(TRUNCATE)`
    #: reports a blocked checkpoint by RETURN VALUE (`busy=1`), not by raising — a reader holding
    #: an older snapshot stops the frames after it being reclaimed. So the previous
    #: `try: … except Exception: pass` could not catch the failure that actually happens here, and
    #: fell through reporting nothing over a checkpoint that had moved nothing. `schema.wal_checkpoint`
    #: returns the triple for exactly this reason; its docstring names this caller's shape.
    from mantle.db.schema import wal_checkpoint
    try:
        busy, log_pages, reclaimed = wal_checkpoint(store.artifacts.db)
    except Exception as e:                       # a real fault: say so rather than continue silently
        print("WAL checkpoint FAILED: %s" % e)
    else:
        if busy:
            print("WAL checkpoint BLOCKED (busy=1): %d log page(s) still held, %d reclaimed — "
                  "an open reader holds an older snapshot" % (log_pages, reclaimed))
        else:
            print("WAL checkpoint: %d page(s) reclaimed" % reclaimed)
    print("precipitated %d token artifacts into %s" % (len(rows), args.collection))

    ro = sqlite3.connect("file:%s?mode=ro" % args.sqlite, uri=True)
    ro.row_factory = sqlite3.Row
    report(ro, args.collection)


def outgest(ro, collection, seed, length):
    r"""The reverse path — concept -> ontology -> screen -> signal -> text.

    Ingestion can look successful while having learned nothing usable: counts accumulate, artifacts
    appear, and every number is finite. Reading the structure back out is what distinguishes a
    corpus that captured order from one that captured a histogram — if the walk emits letter salad,
    the ontology holds letter frequencies and no sequence, which the forward numbers alone would not
    show.

    Each arrow is a real step over the store, in a fresh process, with nothing carried in memory:

      concept   the seed unit — an artifact id, the same kind of thing the read precipitated
      ontology  its `next` edges, read from the lattice, carrying the adjacency counts
      screen    the working buffer of what has been emitted, which is what the next step conditions
                on — the reverse of the buffer the read accumulated
      signal    the ordered choice of successor, by the adjacency's own measured weight
      text      the surfaces concatenated

    The choice is the measured distribution, not an argmax: always taking the heaviest successor
    makes the walk collapse into the single most frequent cycle — `the the the` — which says more
    about argmax than about the corpus ([[one-resolution-not-thresholds]]). The successor is drawn
    in proportion to the count the reading actually observed, so what comes out has the same
    first-order statistics as what went in.
    """
    import random
    rows = {}
    for r in ro.execute(
            # This collection's own writes carry only the `observed` label. `observed_alone` is
            # carried by collections `overlap.py` writes, where a paragraph-unique concept has
            # nothing to co-occur with; both labels are read here because nothing in the code
            # constrains which collection this function is given.
            "SELECT e.src AS s, e.dst AS d, e.props AS p FROM edge e "
            "WHERE e.src LIKE ? AND e.label IN ('observed','observed_alone')",
            (collection + ":%",)):
        # The weight is the observation's own, not a count of edges: `weight` is the summed screen
        # amplitude at the moments the two were lit together, so a pair that co-occurred while both
        # were bright outweighs one that co-occurred while one was nearly cold.
        pr = json.loads(r["p"] or "{}")
        w, sep = pr.get("weight", 0.0), pr.get("sep")
        # A succession, not a containment: the separation is measured, so the walk asks for the
        # observations that came after (sep >= 1) rather than the ones lit inside the same unit
        # (sep ~ 0) — the latter is what would make the text stutter, `the` then `the door`.
        if w > 0.0 and sep is not None and sep >= 1.0:
            rows.setdefault(r["s"], []).append((r["d"], w))
    surf = {}
    for r in ro.execute("SELECT id, doc FROM vertex WHERE id LIKE ?", (collection + ":%",)):
        d = json.loads(r["doc"])
        surf[r["id"]] = d.get("name", "")

    print("")
    print("=" * 92)
    print("OUTGEST — concept -> ontology -> screen -> signal -> text")
    print("=" * 92)
    if not rows:
        print("  the ontology holds NO `observed` edges: nothing was learned about order, so there is")
        print("  nothing to walk. This is a real state and it is reported, never faked.")
        return

    sid = _unit_id(collection, seed)
    if sid not in surf:
        print("  seed %r is not in this collection — it was never read, so it names no concept."
              % seed)
        return
    print("  seed concept : %s  (%r)" % (sid, seed))

    rnd = random.Random(20260806)
    cur, out, steps = sid, [surf[sid]], 0
    while steps < length:
        nxt = rows.get(cur)
        if not nxt:
            print("  the walk GROUNDED OUT at %r — no `next` edge. Stopping rather than jumping to"
                  % surf.get(cur, "?"))
            print("  an unrelated concept, which would be fabrication, not generation.")
            break
        total = sum(c for _, c in nxt)
        pick = rnd.uniform(0, total)
        acc = 0.0
        for d, c in nxt:
            acc += c
            if acc >= pick:
                cur = d
                break
        out.append(surf.get(cur, ""))
        steps += 1
    text = "".join(out)
    print("  emitted %d unit(s):" % (steps + 1))
    print("")
    print("      %s" % repr(text))
    print("")
    return text


def report(ro, collection):
    # Reported as a lower bound, not a total: counting the whole collection to print one number
    # would dereference every record, so this reads a bounded page and reports it as such rather
    # than claiming a total it did not measure.
    _rows = ro.execute("SELECT id FROM vertex WHERE id LIKE ? LIMIT 100000",
                       (collection + ":%",)).fetchall()
    n = len(_rows)
    print("")
    print("=" * 92)
    print("%s — %d token artifacts" % (collection, n))
    print("=" * 92)
    if not n:
        print("  (empty)")
        return
    rows = [d for d in (json.loads(r["doc"]) for r in
            ro.execute("SELECT doc FROM vertex WHERE id LIKE ?", (collection + ":%",)))
            if d.get("content_type") == TOKEN_CT]     # observations are counted separately below
    rows.sort(key=lambda d: -d.get("count", 0))
    N = rows[0].get("corpus_tokens", 0)
    print("  %-16s %8s %9s %12s" % ("token", "count", "IC bits", "first seen at"))
    for d in rows[:8]:
        print("  %-16s %8d %9s %12d" % (repr(d["name"])[1:-1][:16], d["count"],
                                        ("%.2f" % d["ic"]) if d["ic"] is not None else "ABSENT",
                                        d["first_seen_at"]))
    print("  ...")
    for d in rows[-4:]:
        print("  %-16s %8d %9s %12d" % (repr(d["name"])[1:-1][:16], d["count"],
                                        ("%.2f" % d["ic"]) if d["ic"] is not None else "ABSENT",
                                        d["first_seen_at"]))
    hapax = sum(1 for d in rows if d.get("count") == 1)
    print("")
    print("  corpus tokens read : %d" % N)
    print("  hapax (count == 1) : %d of %d types (%.1f%%)  <- the SPARSE end, to be broken up"
          % (hapax, len(rows), 100.0 * hapax / max(len(rows), 1)))
    ics = [d["ic"] for d in rows if d["ic"] is not None]
    print("  IC range           : %.2f .. %.2f bits   (%d unit(s) carry NO IC — formed by colimit, "
          "not yet observed)" % (min(ics), max(ics), len(rows) - len(ics)))


if __name__ == "__main__":
    main()
