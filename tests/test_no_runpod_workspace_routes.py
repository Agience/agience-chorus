"""Guard: the `/workspaces/*` mantle API is not a route in this mantle, and must not become one.

`/workspaces/...` is not mounted — `main.py` includes secrets, downloads, artifacts, gate,
search, issuers, grants, api_keys, platform, servers and events, and there is no workspaces
router anywhere in the repo. A persona call site that hits this prefix returns a 404.

The container model replaces it: a workspace is an artifact, membership is a child edge, so "an
artifact in workspace W" is an artifact created with `container_id=W`, and an artifact is read by
its own id with access decided by the grant light-cone. There is no workspace-scoped route to
restore — that is the point of there being one create path.

This does not guard the astra web frontend's `context/workspaces/` React provider or its
`/workspaces/<id>` UI routes. Those are a UI concept with the same name and are unrelated to the
mantle API — which is why this scans for the MANTLE_URI-joined server path, not for the word.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agience_chorus"
# The chorus PACKAGE root — personas are `agience_chorus.<persona>` subpackages, not bare
# directories under `src/`.


#: The server path, not the word: `MANTLE_URI`-rooted (or a bare quoted path) `/workspaces/...`.
_PATTERNS = (
    re.compile(r"MANTLE_URI[^\n]{0,40}/workspaces/"),
    re.compile(r"""_request\(\s*["'][A-Z]+["']\s*,\s*f?["']/workspaces/"""),
)

#: Personas whose mantle call sites are clean — all seven. Kept as an explicit tuple rather than
#: scanning `src/*` so that a new persona has to be added deliberately, with someone having checked
#: it, instead of silently joining a green check.
CLEANED = ("aria", "astra", "iris", "lumen", "ophan", "sage", "seraph")


def _hits(persona: str, src: Path | None = None) -> list[str]:
    """Hits for one persona. `src` is a parameter, not a monkeypatched global: the seeded-violation
    tests below need to point the scan at a throwaway tree, and patching a module attribute by name
    requires the test module to be importable under that name — which it is not under
    `--import-mode=importlib` with `--rootdir=src`."""
    out = []
    base = src or SRC
    root = base / persona
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue                      # comments may name the dead path without tripping the guard
            if any(p.search(line) for p in _PATTERNS):
                out.append("%s:%d  %s" % (path.relative_to(base).as_posix(), i, line.strip()[:100]))
    return out


def test_the_cleaned_personas_have_no_workspace_routes():
    problems = [h for persona in CLEANED for h in _hits(persona)]
    assert not problems, (
        "the RunPod `/workspaces/*` mantle API is back — it is not a mounted route, so these are 404s:\n  "
        + "\n  ".join(problems))


def test_the_scan_is_actually_scanning():
    """Vacuous-pass guard: if SRC or the personas stopped resolving, the check above passes on nothing."""
    assert SRC.is_dir(), SRC
    for persona in CLEANED:
        assert (SRC / persona).is_dir(), "persona %s not found — the scan would pass vacuously" % persona
    assert list((SRC / "ophan").rglob("*.py")), "no python files found under ophan"


def test_detects_a_seeded_workspace_route(tmp_path):
    """Proof the guard can fail: it must catch a workspace route seeded into a persona tree."""
    fake = tmp_path / "src"
    (fake / "ophan").mkdir(parents=True)
    (fake / "ophan" / "server.py").write_text(
        'url = f"{MANTLE_URI}/workspaces/{ws}/artifacts"\n', encoding="utf-8")
    assert _hits("ophan", fake), "a seeded workspace route was not caught"


def test_the_frontend_workspaces_ui_is_NOT_flagged(tmp_path):
    """The negative control that keeps this guard honest.

    `astra/web` has a legitimate `context/workspaces/` React provider and `/workspaces/<id>` UI routes.
    Matching the bare word would flag them and the obvious 'fix' would be to break the UI. This asserts
    the pattern is specific to the Mantle server path.
    """
    fake = tmp_path / "src"
    (fake / "astra").mkdir(parents=True)
    (fake / "astra" / "ui.py").write_text(
        "ROUTES = ['/workspaces/<id>']\n"
        "IMPORT = 'context/workspaces/WorkspacesContext'\n", encoding="utf-8")
    assert not _hits("astra", fake), "the UI workspaces concept must not be flagged as the dead route"
