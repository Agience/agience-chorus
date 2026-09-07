# authoritative home: operator code lives in chorus, with a single path — no mirrors. Distributed to
# hosts as a content-addressed source bundle (bundle_spec.json + the tekton below); ember executes
# it via ember/runner.py, sha-verified before exec. Changes happen here.
"""Bundle production as an organon and a tekton — the producer half of the distribution path.

Information is moved by tektons, organons and facets only — never by a script a human runs
one-off, wired to no capability.

    op.bundle.observe   organon — reaches the source tree where it actually lives: reads the spec
                        and each declared module's text off disk. Computes nothing, normalises
                        nothing, touches no store. An organon reaches; it does not judge.
    op.bundle.condense  tekton (domain: distribution) — sources in, the canonical payload and its
                        sha out. Denser information: N module texts become one addressable,
                        verifiable artifact that a node can load without trusting the transport.

The split is not cosmetic: normalisation is interpretation — it is part of deciding what gets
signed, so it belongs to the condensation, not to the reach. Split this way, the source can move
(a git remote, a mesh peer, a working tree) without the canonicalisation changing, which is the
same property that makes `op.canon.source` worth separating from `op.canon.condense`.

The sha is not defined here. `prism.crystal_model.bundle_canonical` is the contract, and the runner
verifies with the same function — so producer and consumer cannot drift into disagreeing about what
was signed. A second definition of the canonical form would be a second declaration of the thing
being signed, and drift in a sha is silent.

What this deliberately does not do: land bundle artifacts in the live store. The mesh path is
artifact `bundle-<group>`, and `runner.verify_provenance` requires a `created_by` that resolves
there, which needs a resolvable principal and an operator's explicit decision to land on a given
node — not something an agent decides. The tekton produces payloads and lands them where the need
says, to the shipped directory only.

The check that a bundle matches its claimed source lives outside chorus, deliberately: chorus
building the payloads and also checking them would be a producer grading its own homework, catching
nothing its own reader gets wrong. `agience-cloud/deploy/test_bundles_are_what_they_claim.py` walks
the spec and the disk independently, and catches a tampered payload that a same-process check would
report as unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: Organon — reach the source tree. Tekton — condense it into signed-shaped payloads.
BUNDLE_OBSERVE_CAP = "op.bundle.observe"
BUNDLE_CONDENSE_CAP = "op.bundle.condense"

#: The declaration the organon reads. Relative to the workspace root the NEED names.
#:
#: Both of these named `agience-observe` until the payloads moved here. They are chorus's output —
#: every module the spec names is `agience-chorus/src/...` — and observe was hosting them only
#: because it is where the build CLI happens to live. That made a repository whose job is to RUN
#: things the home of another repository's build artifacts, and it put every consumer's checkout of
#: the payloads behind observe rather than behind their source.
#: Beside this module, which is the capability that reads it. NOT inside `bundles/`: that
#: directory is enumerated by globbing `*.json`, one file per group, so a spec sitting there is
#: picked up as a group named "spec" — measured, not guessed.
SPEC_NAME = "agience-chorus/src/seraph/bundle_spec.json"

#: Where the shipped payloads live — the runner's fallback when the store has no `bundle-<group>`.
SHIPPED_DIR = "agience-chorus/bundles"

__all__ = ["BUNDLE_OBSERVE_CAP", "BUNDLE_CONDENSE_CAP", "SPEC_NAME", "SHIPPED_DIR",
           "observe", "condense", "bundle_observe_handler", "bundle_condense_handler",
           "register_bundling_operators"]


# ── the organon — reach the source, interpret nothing ────────────────────────────────────────
def observe(root: str, *, groups: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Read the spec and every declared module's source text, raw.

    The source path is pinned per module and never searched by basename: resolving `operators` by
    filename would find two files — `sage/operators.py` and `iris/comms/operators.py` — and a
    search would silently pick one, the same duplicate-basename substitution this workspace has
    been bitten by before [[pytest-module-shadowing-silent-substitution]]. A declared path that has
    moved must fail loudly.

    Returns text exactly as it sits on disk — CRLF and all. Normalising here would mean the reach
    deciding what gets signed.
    """
    base = Path(root)
    spec = json.loads((base / SPEC_NAME).read_text(encoding="utf-8"))
    want = list(groups) if groups else sorted(spec)
    unknown = [g for g in want if g not in spec]
    if unknown:
        raise KeyError("unknown group(s): %s; declared: %s"
                       % (", ".join(sorted(unknown)), ", ".join(sorted(spec))))

    out: List[Dict[str, Any]] = []
    for group in want:
        decl = spec[group]
        modules, paths = {}, {}
        for name, rel in sorted(decl["modules"].items()):
            path = base / rel
            if not path.is_file():
                raise FileNotFoundError(
                    "%s/%s: declared source is not at %s. The module moved — update %s. The reach "
                    "does NOT fall back to a basename search, which is how the wrong `operators.py` "
                    "gets shipped." % (group, name, rel, SPEC_NAME))
            modules[name] = path.read_text(encoding="utf-8")
            paths[name] = rel
        out.append({"group": group, "entry_module": decl["entry_module"],
                    "register_fns": list(decl["register_fns"]),
                    "host_seams": list(decl["host_seams"]),
                    "modules": modules, "paths": paths})
    return out


def bundle_observe_handler(root: str) -> Callable[[Any], List[Dict[str, Any]]]:
    """Organon handler. NEED is `{}` (or `{root}` / `{groups}`); the answer is the raw source with
    the paths it came from."""
    def handler(need: Any) -> List[Dict[str, Any]]:
        need = need or {}
        return observe(str(need.get("root") or root), groups=need.get("groups"))
    return handler


# ── the tekton — sources in, one verifiable payload out ──────────────────────────────────────
def condense(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Condense observed source into canonical, sha-addressed payloads.

    Newlines are normalised here, and this is the step that decides what is signed: a CRLF
    checkout on Windows and an LF checkout on Linux must not produce two different bundles for
    identical source. Doing it in the reach would hide a decision inside a read.

    Pure — touches no store and no filesystem, so it is trivially testable and the landing is a
    separate, explicit act.
    """
    from prism.crystal_model import bundle_canonical
    out: List[Dict[str, Any]] = []
    for obs in observations:
        bundle = {
            "group": obs["group"],
            "entry_module": obs["entry_module"],
            "register_fns": list(obs["register_fns"]),
            "host_seams": list(obs["host_seams"]),
            "modules": {n: t.replace("\r\n", "\n") for n, t in sorted(obs["modules"].items())},
        }
        bundle["sha256"] = hashlib.sha256(bundle_canonical(bundle)).hexdigest()
        out.append(bundle)
    return out


def bundle_condense_handler(root: str) -> Callable[[Any], Dict[str, Any]]:
    """Tekton handler (domain: distribution). NEED is `{}`; the answer says what each group's payload
    now is and whether it moved.

        {"groups": [...]}  condense only these
        {"land": true}     write the payloads to the shipped dir (the runner's fallback path)

    It reaches the source through the organon, never the filesystem directly — that is what keeps
    this the only production path and lets the source move without the condensation changing.

    Landing is off by default: a tekton answering a question must not write as a side effect, so the
    need asks for it explicitly. It lands only to the shipped directory — never to the live store,
    which needs a resolvable principal and an operator's explicit decision.
    """
    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        base = str(need.get("root") or root)
        payloads = condense(bundle_observe_handler(base)(need))
        shipped = Path(base) / SHIPPED_DIR
        land = bool(need.get("land", False))

        groups: Dict[str, Any] = {}
        moved, landed = [], []
        for bundle in payloads:
            group = bundle["group"]
            path = shipped / ("%s.json" % group)
            was = None
            if path.is_file():
                try:
                    was = json.loads(path.read_text(encoding="utf-8")).get("sha256")
                except Exception:
                    was = None                      # unreadable == absent; the rebuild decides
            same = (was == bundle["sha256"])
            if not same:
                moved.append(group)
                if land:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n",
                                    encoding="utf-8")
                    landed.append(group)
            groups[group] = {"sha256": bundle["sha256"], "was": was, "moved": not same}
        return {"groups": groups, "moved": sorted(moved), "landed": sorted(landed),
                "shipped_dir": SHIPPED_DIR, "landed_anything": bool(landed)}
    return handler


# ── registration ─────────────────────────────────────────────────────────────────────────────
_BUNDLING_OPS = [
    (BUNDLE_OBSERVE_CAP,
     "ORGANON: reaches the operator SOURCE TREE where it lives and returns each declared module's "
     "raw text with the path it came from. Pins every path from the spec and refuses a moved module "
     "loudly — it never falls back to a basename search, which is how the wrong `operators.py` gets "
     "shipped. Computes no sha and normalises nothing, so the source can move without the "
     "condensation changing"),
    (BUNDLE_CONDENSE_CAP,
     "TEKTON (domain: distribution): condenses observed source into a canonical, sha-addressed "
     "PAYLOAD a node can verify before exec — the producer half of the one distribution path, whose "
     "consumer is op.install. Normalises newlines (that is the step deciding what is signed) and "
     "computes the sha through prism's bundle_canonical, the SAME function the runner verifies "
     "with, so producer and consumer cannot drift. Writes nothing unless the NEED asks to land"),
]


def register_bundling_operators(store, *, author: str = "seraph-bundling") -> int:
    """Register seraph's bundle-production capabilities."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _BUNDLING_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "seraph bundling operator %s: %s" % (name, offer),
            "created_by": author}))
    return len(_BUNDLING_OPS)
