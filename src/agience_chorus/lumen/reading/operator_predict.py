r"""Predicts from a read book: the operator is the model, and it is measured, not trained.

    python node/predict.py --text <corpus-dir>/pride.txt --seed "Mr. Darc"

Every token is a step, so the corpus is a trajectory rather than a static frame, and the instrument
is the dynamical one: `koopman_lift` fits the operator, `predict` advances it. There is no training,
no weights, and no hypothesis class — the operator is read off the trajectory the book already is.

Measured on Pride & Prejudice, 50,000 characters, no other input of any kind:

    'Mr. Darc'   ->  +1  'y' 0.68   (next best 0.078)
                     +2  ' ' 0.352
    'acknowledg' ->  +1  'e' 0.137
    'very m'     ->  +1  'o' 0.174, 'a' 0.171, 'e' 0.169   +2 'n' 0.167

How far the operator may be rolled is its own answer, not a chosen rollout length:

    l = ceil( ln(contrast) / (-ln m) )        m = |mu| of the dominant mode

`contrast = lambda1 / edge` is published by the instrument, so the floor and the amplitude it bounds
come from one spectrum and no scale survives the division. Past `l` the operator is predicting from
an amplitude it no longer has; rolling past the horizon reports the operator's own decay rather than
a broken instrument.

The horizon derivation is `lumen/reasoning._operator_horizon`'s. Using `noise_floor` raw — an
eigenvalue edge, O(1), never inside (0,1) — makes `ln(1/eps)` negative and the horizon read as
already over; `eps = 1/contrast` keeps it inside (0,1).

The frame must have more rows than features: with too few rows relative to features, the correlation
is degenerate and `resolved_modes` is 0 regardless of signal, which reads like the instrument cannot
see text. `window = rows_per_feature * F` is the guard, and this file states T and F in its output so
an under-sampled read is not mistaken for an absent signal.

Two things here are chosen rather than measured: the delay depth, and the one-hot encoding.
Everything else on this page is read off the instrument.
"""
import argparse
import math
import os
import sys

import numpy as np


def body(path):
    """The stream, exactly as given — no regex, no stripping. Stripping a publisher's wrapper is a
    question about the data and is done once, outside (see organon.book_text)."""
    return open(path, encoding="utf-8", errors="replace").read()


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--text", required=True)
    ap_.add_argument("--seed", action="append", default=[])
    ap_.add_argument("--chars", type=int, default=50000, help="how much of the stream to read")
    ap_.add_argument("--depth", type=int, default=4, help="delay depth — CHOSEN, not measured")
    ap_.add_argument("--rows-per-feature", type=int, default=8,
                     help="instrument rows per feature; T must exceed F or the correlation is degenerate")
    args = ap_.parse_args()

    # One instrument. `test_only_the_instrument_seam_imports_entroptics` forbids `from entroptics import ...`
    # here, because the bare door applies the entropy fold guard that destroys a sparse carrier. The
    # operator, its horizon, and the rule that it may not be rolled past it live in `ember/optics.py`
    # and are reached by name, via the host seam.
    from agience_chorus._host_seams import seam as _seam
    _optics = _seam("optics")

    text = body(args.text)[:args.chars]
    alpha = sorted(set(text))
    idx = {c: i for i, c in enumerate(alpha)}
    inv = {i: c for c, i in idx.items()}

    def onehot(s):
        a = np.zeros((len(s), len(alpha)))
        for i, c in enumerate(s):
            a[i, idx[c]] = 1.0
        return a

    W = onehot(text)
    op = _optics.sequence_operator(
        W, depth=args.depth, window_rows_per_feature=args.rows_per_feature)
    if op is None:
        print("the stream is too short to embed at depth %d — nothing to fit" % args.depth)
        return

    print("stream %d chars, alphabet %d" % (len(text), len(alpha)))
    print("instrument: contrast %.4f  resolved_modes %d" % (op.contrast, op.resolved_modes))
    print("operator: margin %.4f" % op.margin)
    if op.horizon is None:
        print("")
        print("HORIZON: none — %s. The operator is not rolled at all; that is a refusal with a "
              "reason behind it, not an empty answer." % op.refusal)
        return
    print("HORIZON %d step(s)   l = ceil(ln(contrast)/-ln m)" % op.horizon)

    for seed in (args.seed or ["Mr. Darc", "It is a truth universally acknowledg", "she was very m"]):
        if any(c not in idx for c in seed):
            print("")
            print("%r — contains a character this reading has never seen; nothing to predict from"
                  % seed)
            continue
        x = _optics.embed(onehot(seed), args.depth)[-1]
        print("")
        print("%r" % seed)
        # No argmax, and no step past the horizon: `roll()` hands back the whole distribution and
        # stops at l, so this loop cannot overrun it.
        for step, dist in op.roll(x):
            order = np.argsort(-np.abs(dist))
            share = [(inv[int(i)], round(float(dist[i]), 3)) for i in order[:6]]
            print("   +%d  %s" % (step, share))


if __name__ == "__main__":
    main()
