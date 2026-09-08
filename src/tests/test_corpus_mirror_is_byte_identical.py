"""The ember original of the corpus index must stay behaviourally identical to this copy.

The chorus half of a two-sided ratchet. `agience-ember/tests/test_corpus_mirror_is_byte_identical.py`
holds the other half, and the reasoning is written out there in full. The short version:

`corpus_fts.py` and `corpus_stats.py` in this repo are copies of `ember/corpus/fts.py` and
`ember/ontology/corpus_stats.py`. The copy is FORCED — `test_chorus_does_not_import_ember.py`
asserts `chorus -> ember` is zero in both directions, and mantle deleted the original — so it must
not be merged away. But an ember node WRITES the index a sage query READS, so a divergence in the
schema, tokenizer, stemmer or ranking **silently re-ranks the corpus** rather than raising.

Both repos check, so the invariant survives a change made from either side, and neither repo's
suite can be green while the two disagree.

See the ember file for what is compared (the AST with the module docstring dropped), which two
identity differences are permitted, and the negative controls.
"""
from __future__ import annotations

import ast
import difflib
from pathlib import Path

import pytest

# `src/tests/` -> `src/` -> repo root -> the sibling checkout.
_CHORUS = Path(__file__).resolve().parents[2]
_EMBER = _CHORUS.parent / "agience-ember"

#: (this repo's file, the ember original, [(ours, theirs, canonical), ...]).
#: `canonical` must be valid Python — the normalised source is re-parsed.
_MIRRORS = [
    (
        _CHORUS / "src" / "agience_chorus" / "corpus_fts.py",
        _EMBER / "src" / "ember" / "corpus" / "fts.py",
        [('logging.getLogger("chorus.corpus_fts")',
          'logging.getLogger("ember.corpus.fts")',
          'logging.getLogger("<mirror>")')],
    ),
    (
        _CHORUS / "src" / "agience_chorus" / "corpus_stats.py",
        _EMBER / "src" / "ember" / "ontology" / "corpus_stats.py",
        # Each side names the index the way its own package does — chorus qualifies
        # (`agience_chorus.corpus_fts`), ember reaches its subpackage (`ember.corpus.fts`). Both
        # normalise to one canonical line so the comparison is of BEHAVIOUR, not of how the two
        # trees happen to be laid out.
        [("import agience_chorus.corpus_fts as _fts",
          "from ember.corpus import fts as _fts",
          "import _mirror_fts as _fts")],
    ),
]


def _behaviour(path: Path, swaps, *, is_theirs: bool) -> str:
    src = path.read_text(encoding="utf-8-sig")
    for ours, theirs, canonical in swaps:
        src = src.replace(theirs if is_theirs else ours, canonical)
    tree = ast.parse(src, filename=str(path))
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        tree.body = tree.body[1:]
    return ast.dump(tree, indent=1)


@pytest.mark.parametrize("ours,theirs,swaps", _MIRRORS, ids=lambda p: getattr(p, "name", ""))
def test_the_ember_original_is_behaviourally_identical(ours: Path, theirs: Path, swaps):
    if not theirs.exists():
        pytest.skip(f"ember is not checked out beside chorus ({theirs} absent)")
    assert ours.exists(), f"{ours} is missing — this repo's copy of the mirror is gone"

    a = _behaviour(ours, swaps, is_theirs=False)
    b = _behaviour(theirs, swaps, is_theirs=True)
    if a == b:
        return

    diff = "\n".join(list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), fromfile=str(ours), tofile=str(theirs), lineterm="", n=2,
    ))[:80])
    pytest.fail(
        f"\n{ours.name} and its ember original have DIVERGED BEHAVIOURALLY.\n\n"
        f"  ours   : {ours}\n  theirs : {theirs}\n\n"
        "An ember node writes the index a sage query reads. A divergence here does not raise at "
        "runtime — it silently re-ranks the corpus. Make the change in BOTH copies, in the same "
        "commit.\n\n"
        f"AST diff (module docstring excluded, first 80 lines):\n{diff}"
    )


def test_the_comparison_can_actually_fail():
    """Negative control — a blind comparison would make this ratchet decorative."""
    def dump(s: str) -> str:
        return ast.dump(ast.parse(s), indent=1)

    assert dump("import re\nX = re.compile(r'[a-z]+')\n") != \
           dump("import re\nX = re.compile(r'[a-z0-9]+')\n"), \
           "the AST comparison is blind to a changed regex"
