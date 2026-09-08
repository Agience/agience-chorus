"""Chorus-wide pytest fixtures.

Persona tools sign outbound JWTs via ``origin.service_identity.sign_service_jwt``.
That module raises if no service identity has been loaded — normally the
chorus host's lifespan calls ``init_service_identity("chorus")`` after the
init container has written ``chorus.private.pem`` and the authority manifest.

Tests don't run the lifespan, so we materialize a throwaway chorus keypair
+ minimal authority manifest in a tmp dir and initialize service identity
once for the whole test session. Cleanup restores the original KEYS_DIR so
later test files (e.g. mantle's authority-content tests) don't see chorus's
fake manifest.
"""
from __future__ import annotations

# ── the operator payloads ───────────────────────────────────────────────────────────────────────
#
# `prism.runner` resolves an operator group to a sha-verified payload, and there is no in-package
# copy to fall back to: a second copy of a content-addressed payload can drift from the one the mesh
# carries, and the sha gate would then verify the wrong bytes faithfully. Without them, several
# modules here fail at IMPORT with `UnknownBundleGroupError`.
#
# They are THIS repository's own — chorus builds them from chorus source — so there is nothing to
# find and nothing to configure. Set before any test module imports, and `setdefault` so a caller
# who names a different root still wins.
import os as _os
from pathlib import Path as _Path

_os.environ.setdefault(
    "AGIENCE_BUNDLE_ROOT",
    str(_Path(__file__).resolve().parent / "agience_chorus" / "bundles"))

# This test process's observer identity. Mantle's sqlite store REFUSES to open without one, and it
# is right to: `(_origin, _seq)` is the store's only version identity, so a node that generated an
# id per boot would fork its own proper time and leave peers with two permanently-unordered event
# streams. A test process has no proper time to fork — each store fixture writes into its own
# `tmp_path` lattice and discards it — but it does need the id to be STABLE within a run, which a
# literal gives exactly.
#
# Here rather than in the four fixtures that open a store, so the fifth one written does not
# rediscover this. `setdefault`, so a developer machine that pins a real node id still wins and
# nothing about a deployment changes: only a process that named none gets this.
_os.environ.setdefault("EMBER_NODE_ID", "chorus-test")

# ── ember's shared test doubles ─────────────────────────────────────────────────────────────────
#
# The tests that exercise chorus's operators THROUGH ember's runner live here, because that is where
# the payloads are. They use ember's `_FakeStore` — a double for mantle's store, ~160 lines with
# `_FakeArtifacts` and `_FakeGraph` behind it.
#
# Reached rather than copied. A second copy of a double that models another repository's API is a
# copy that drifts, and the drift is silent: the stale side keeps passing against a store shape that
# no longer exists. There is one copy, in ember, and this puts it on the path.
#
# Found by climbing to the workspace, the same way everything else here locates a sibling. Absent an
# ember checkout the path is simply not added, and the tests that need it fail to import — which is
# the honest signal, since without ember there is no runner to test through.
import sys as _sys

# TWO layouts are real. In a developer workspace the repos are siblings, so climbing the parents
# reaches `agience-ember`. In CI they are not: `actions/checkout` cannot write above the workspace,
# so it puts them under `<repo>/.siblings/`, which is a CHILD of a parent and no climb ever visits
# it. Both are probed at each level, or the CI run adds nothing and the tests that need the doubles
# skip — green, having compared nothing, which is the one outcome worth guarding against here.
_probe = _Path(__file__).resolve()
for _up in _probe.parents:
    for _cand in (_up / "agience-ember" / "tests", _up / ".siblings" / "agience-ember" / "tests"):
        if _cand.is_dir():
            if str(_cand) not in _sys.path:
                _sys.path.append(str(_cand))   # append: chorus's own helpers win on a name clash
            # Published for SUBPROCESSES. `sage/tests/_recognition_probe.py` runs in its own
            # interpreter — it must, because it blocks `ember` at the meta-path for the requester
            # while the provider needs it — and a child inherits the environment, never the
            # parent's runtime `sys.path`. It used to derive this from `ember.__file__` by walking
            # up three directories, which is the repo root for an EDITABLE install and
            # `lib/python3.12` for a regular one; CI installs ember regularly, so it found nothing.
            # This process already resolved the real directory, so it says where rather than
            # letting each child re-derive it from a layout assumption.
            _os.environ.setdefault("AGIENCE_EMBER_TESTS", str(_cand))
            break
    else:
        continue
    break
del _os, _Path, _sys, _probe

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk

# The fixture body lives in `_chorus_identity.py` so it has one home and can be registered by more
# than one conftest.
from agience_chorus._chorus_identity import _chorus_test_identity  # noqa: F401  (registers the fixture here)

# ── this test process is the host, and says so ──────────────────────────────────────────────────
# Persona modules declare `ember.{ontology.match, ontology.activation, signal.projection,
# runtime.delegate}` by name through `_host_seams.seam(...)` rather than importing them directly.
# Which module fills a seam is the host's answer; in a live deployment the host is the ember
# runner, whose `ember/__init__.py` binds all four.
#
# A test process has no runner, so without this import the seams are unfilled and every persona
# path that measures takes its honest refusal — leaving the suite green against degraded behaviour
# rather than against the behaviour it is meant to pin. Importing ember here does exactly what
# booting a runner does (registration is four dotted strings; nothing is loaded until a seam is
# actually reached) and nothing more.
#
# This import belongs in conftest, not in `src/`: a conftest is test scaffolding, and standing in
# for the host is what scaffolding is for. `test_chorus_does_not_import_ember.py` and
# `test_persona_bundle_conversion_status.py` both fail on a `register_seam` call in shipped code,
# so the seam fill happens here instead.
import ember  # noqa: F401,E402  — binds ember's host seams; see `ember/runtime/seams.py`
