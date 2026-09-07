r"""Aria, answering with the operator read off one book.

    python node/aria-read.py --text <corpus-dir>/pride.txt --port 8096
    → http://127.0.0.1:8096/chat

The operator is the model. Every token is a step, so the book is a trajectory; `koopman_lift`
reads the operator off it and `predict` advances it. Nothing is trained and there are no weights —
`Elizabeth Benne` -> `t` because the operator carries Bennet, having read the book.

How far it may speak is its own answer: `l = ceil(ln(contrast)/(-ln m))`, the step at which the
dominant mode decays to the frame's own floor. `contrast = lambda1/edge` is published by the
instrument, so both numbers come from one spectrum and no scale survives the division. Past `l` the
operator predicts from an amplitude it does not have.

Generation re-seeds rather than extrapolating. Each emitted character is appended and the state
re-formed from the text, so every step is one step from a real state, never step 40 of a decayed
one. The appended character is predicted, not observed, so error compounds along the reply — a
property of this loop, not of the operator.

What is chosen here is named: the delay depth and the one-hot encoding are set by this module. The
horizon, the margin, the resolved modes, the contrast and the floor are the instrument's.
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


def build(text_path, chars, depth, rows_per_feature, reply, seed_rng):
    # One instrument, reached by name. See the note in `operator.py`.
    from _host_seams import seam as _seam
    _optics = _seam("optics")

    text = body(text_path)[:chars]
    alpha = sorted(set(text))
    idx = {c: i for i, c in enumerate(alpha)}
    inv = {i: c for c, i in idx.items()}

    def onehot(s):
        a = np.zeros((len(s), len(alpha)))
        for i, c in enumerate(s):
            a[i, idx[c]] = 1.0
        return a

    W = onehot(text)
    op = _optics.sequence_operator(W, depth=depth, window_rows_per_feature=rows_per_feature)
    rng = np.random.default_rng(seed_rng)

    print("[aria] %d chars, alphabet %d" % (len(text), len(alpha)), file=sys.stderr)
    print("[aria] contrast %.4f  resolved_modes %d  margin %.4f  horizon %s"
          % (op.contrast, op.resolved_modes, op.margin, op.horizon) if op else "[aria] unreadable",
          file=sys.stderr)

    def respond(q):
        q = (q or "").strip()
        if op is None or op.horizon is None:
            return {"answer": "", "cited": [], "grounded": False,
                    "read": {"refused": (op.refusal if op else
                                         "the stream is too short to embed at this depth")}}
        known = [c for c in q if c in idx]
        if len(known) < depth:
            # No state to advance from, so nothing is said; the fields report why.
            return {"answer": "", "cited": [], "grounded": False,
                    "read": {"refused": "too little of this has been read to form a state",
                             "recognised": len(known), "needed": depth}}
        seed = "".join(known)
        out, blk = [], None
        for _ in range(reply):
            x = _optics.embed(onehot(seed[-max(depth * 4, 32):]), depth)[-1]
            # one step, taken from the instrument's own roll — so emitting a long reply can never
            # drift past the horizon: each character re-seeds from what has actually been said.
            blk = next((d for _s, d in op.roll(x)), None)
            if blk is None:
                break
            # The one forced act in this file. The prediction is a distribution; emitting text has
            # to choose a character. It is drawn from the operator's own distribution, never from
            # its maximum — an argmax collapses every reply onto the same attractor — and the first
            # step's shares ride out in `read` so the choice is visible.
            w = np.clip(blk.astype(float), 0.0, None)
            if not w.sum():
                break
            out.append(inv[int(rng.choice(len(alpha), p=w / w.sum()))])
            seed += out[-1]
        said = "".join(out)
        order = np.argsort(-np.abs(blk)) if blk is not None else []
        return {"answer": said, "cited": [os.path.basename(text_path)], "grounded": bool(said),
                "read": {"horizon": op.horizon, "contrast": round(op.contrast, 4),
                         "resolved_modes": int(op.resolved_modes), "margin": round(op.margin, 4),
                         "last_step": [(inv[int(i)], round(float(blk[i]), 3)) for i in order[:6]]}}

    return respond


def main():
    p = argparse.ArgumentParser()
    # The text is a corpus file, not part of the checkout: the caller names it.
    p.add_argument("--text", required=True, help="the text to read")
    p.add_argument("--chars", type=int, default=50000)
    p.add_argument("--depth", type=int, default=4, help="delay depth — CHOSEN, not measured")
    p.add_argument("--rows-per-feature", type=int, default=8)
    p.add_argument("--reply", type=int, default=120)
    p.add_argument("--rng", type=int, default=20260806)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8096)
    p.add_argument("--ask", default="")
    args = p.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    # `src/lumen/reading` -> four hops up is the workspace root that holds every sibling checkout.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    # entroptics is a MEMBER of this workspace since the three workspaces merged into
    # `Repos/agience/` — it used to be `../entroptics/entroptics-viewer`.
    # `ember/optics.py` refuses the older `<workspace>/agience-entroptics` copy by name, so a
    # stale entry here does not silently bind the wrong tree; it fails at import.
    for sub in ("entroptics/src", "agience-chorus/src", "agience-prism/py/src"):
        sys.path.insert(0, os.path.abspath(os.path.join(root, sub)))

    responder = build(args.text, args.chars, args.depth, args.rows_per_feature,
                      args.reply, args.rng)

    if args.ask:
        import json
        print(json.dumps(responder(args.ask), indent=1))
        return

    # Lumen may not import aria: a persona reaches a sibling over the ground plane, never by
    # importing it, or it cannot be deployed on its own. Wiring lumen's responder into aria's bff is
    # the host's act — `chorus/personas.py::_wire_conversation_carrier` is the component allowed to
    # see both — so this module exports the responder and wires nothing.
    raise SystemExit(
        "serving is the host's act, not lumen's. Build the responder with `build(...)` and let "
        "`chorus/personas.py::_wire_conversation_carrier` place it on aria's bff; a persona that "
        "imports a sibling cannot be deployed alone. Use --ask to exercise the responder here.")


if __name__ == "__main__":
    main()
