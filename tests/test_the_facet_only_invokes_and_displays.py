"""Guard: the Facet only invokes, displays, and calls the Mantle and Crystal APIs.

Everything is an artifact, and all code that touches information lives in an artifact. The Facet
(`astra/web/src`) holds none of it: no filtering, sorting, counting or de-duplicating of artifacts,
no ownership or role checks, no list of types, and no information kept in the browser beyond the
viewer's own preferences.

The scan greps the Facet source, leaving out `api/`, `display-state/`, tests and comment lines, for
the shapes that logic takes. `display-state/` holds the screen's own lists (what the viewer has
selected, opened, dragged or typed) as helpers over any list of keys; it imports nothing, so it can
reach no artifact, type or person. Every site that has the shapes today is listed in
`facet-rule-allowlist.txt`, one line per site, with the audit row and the build that removes it. The list only shrinks:

- a hit that is not in the list fails;
- a line in the list that no longer matches a hit fails, so a fixed site leaves the list;
- the list must hold exactly `CEILING` lines. A build that removes sites lowers `CEILING` by the
  number it removed; nothing raises it.

A line is keyed by file, pattern and the site's own text, not its line number, so an edit elsewhere
in a file does not move it.

Some logic has no shape a pattern sees: a hardcoded list, a parser, a constant. Once a build removes
one, its name goes in `facet-banned-names.txt` and may not come back anywhere in the Facet, `api/`,
tests and comments included. A name is an identifier, matched as a whole word; a path ending in a
source suffix is a file, which may not exist and may not be imported.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FACET = REPO / "src" / "agience_chorus" / "astra" / "web" / "src"
ALLOWLIST = Path(__file__).with_name("facet-rule-allowlist.txt")
BANNED = Path(__file__).with_name("facet-banned-names.txt")

#: The number of lines in the allowlist. It only goes down.
CEILING = 12

#: The shapes information logic takes in the Facet, by name.
PATTERNS = {
    "filter": re.compile(r"\.filter\("),
    "sort": re.compile(r"\.sort\("),
    "reduce": re.compile(r"\.reduce\("),
    "set": re.compile(r"new Set\("),
    "localeCompare": re.compile(r"localeCompare"),
    "created_by": re.compile(r"created_by\s*[!=]==|[!=]==\s*[\w.?]*created_by\b"),
    "roles": re.compile(r"roles\??\.includes"),
    "role-name": re.compile(r"""['"](owner|editor|viewer|platform:admin)['"]"""),
    "content-type": re.compile(r"application/vnd\.agience\."),
    "storage": re.compile(r"localStorage\.setItem\(\s*(?P<key>[^,)]*)"),
}

#: localStorage keys that hold the viewer's own preferences: layout, the last open tab, filters
#: they hid, the cookie notice. Anything else kept in the browser is information.
PREFERENCE_KEYS = {
    "COOKIE_PREF_KEY",
    "lastTabKey",
    "HIDDEN_CONTENT_TYPE_FILTERS_STORAGE_KEY",
    "STACKED_ARTIFACT_FAMILIES_STORAGE_KEY",
}
#: A preference key held in a local variable, by the file that builds it.
PREFERENCE_SITES = {("utils/desktop-layout.ts", "key")}

SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")

#: The Mantle and Crystal clients, and the screen's own lists.
SKIPPED = ("api", "display-state")
DISPLAY_STATE = FACET / "display-state"
IMPORT = re.compile(r"^\s*(import\b|export\b[^;]*\bfrom\b)|\brequire\(|\bimport\(")


def _is_test(rel: Path) -> bool:
    return "__tests__" in rel.parts or any(s in rel.name for s in (".test.", ".spec."))


def _is_comment(text: str) -> bool:
    return text.startswith(("//", "/*", "*"))


def scan(root: Path = FACET) -> Counter:
    """Every site as (file, pattern, text), counted, so two identical sites in a file are two."""
    sites: Counter = Counter()
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in SKIPPED or _is_test(rel):
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text or _is_comment(text):
                continue
            for name, pattern in PATTERNS.items():
                found = pattern.search(text)
                if not found:
                    continue
                if name == "storage":
                    key = found.group("key").split("(")[0].strip()
                    if key in PREFERENCE_KEYS or (rel.as_posix(), key) in PREFERENCE_SITES:
                        continue
                sites[(rel.as_posix(), name, text)] += 1
    return sites


def read_allowlist(path: Path = ALLOWLIST) -> tuple[Counter, int]:
    """Lines are `row N | build B | file | pattern | text`; `#` lines and blank lines are notes."""
    listed: Counter = Counter()
    lines = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split(" | ", 4)
        assert len(parts) == 5, f"malformed allowlist line: {raw!r}"
        _row, _build, file, name, text = parts
        listed[(file, name, text)] += 1
        lines += 1
    return listed, lines


def _show(sites) -> str:
    return "\n".join(f"  {f} [{n}] {t}" for f, n, t in sorted(sites))


def test_the_facet_adds_no_information_logic():
    listed, _ = read_allowlist()
    new = scan() - listed
    assert not new, (
        "The Facet only invokes and displays. Move this logic into an artifact (a type, an "
        "operator, or a Mantle or Crystal answer); the allowlist does not take new lines:\n"
        + _show(new))


def test_a_fixed_site_leaves_the_allowlist():
    listed, _ = read_allowlist()
    gone = listed - scan()
    assert not gone, (
        "These allowlist lines match nothing now. Remove them and lower CEILING by as many:\n"
        + _show(gone))


def test_the_allowlist_only_shrinks():
    _, lines = read_allowlist()
    assert lines == CEILING, (
        f"The allowlist holds {lines} lines and CEILING is {CEILING}. Lines leave it as sites are "
        "fixed and CEILING drops with them; it never grows.")


def test_the_scan_sees_a_seeded_violation(tmp_path):
    (tmp_path / "components").mkdir()
    (tmp_path / "api").mkdir()
    (tmp_path / "components" / "Bad.tsx").write_text(
        "const mine = items.filter(a => a.created_by === me);\n"
        "// items.sort() in a comment is not a site\n"
        "localStorage.setItem('access_token', t);\n"
        "localStorage.setItem(COOKIE_PREF_KEY, 'true');\n", encoding="utf-8")
    (tmp_path / "api" / "client.ts").write_text("rows.sort();\n", encoding="utf-8")
    names = {name for (_f, name, _t) in scan(tmp_path)}
    assert names == {"filter", "created_by", "storage"}
    assert sum(scan(tmp_path).values()) == 3


def display_state_imports(root: Path = DISPLAY_STATE) -> list[str]:
    """Each line in `display-state/` that imports anything, other than another display-state file."""
    hits = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if IMPORT.search(line) and not re.search(r"""from\s+['"]\./""", line):
                hits.append(f"{path.relative_to(root).as_posix()}:{number} {line.strip()}")
    return hits


def test_the_screens_own_lists_reach_nothing():
    assert DISPLAY_STATE.is_dir()
    hits = display_state_imports()
    assert not hits, (
        "display-state/ holds helpers over any list of keys and imports nothing; logic that needs "
        "an artifact, a type or a person lives in an artifact:\n" + "\n".join(f"  {h}" for h in hits))


def display_state_literals(root: Path = DISPLAY_STATE) -> list[str]:
    """Each line in `display-state/` that names a role or an artifact content type."""
    named = (PATTERNS["role-name"], PATTERNS["content-type"])
    hits = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.search(line) for p in named):
                hits.append(f"{path.relative_to(root).as_posix()}:{number} {line.strip()}")
    return hits


def test_the_screens_own_lists_name_no_role_or_type():
    hits = display_state_literals()
    assert not hits, (
        "display-state/ names no role and no artifact content type; those come from Mantle and the "
        "type artifacts:\n" + "\n".join(f"  {h}" for h in hits))


def test_the_literal_check_sees_a_seeded_name(tmp_path):
    (tmp_path / "a.ts").write_text(
        "const r = 'editor';\nconst t = 'application/vnd.agience.view+json';\nconst k = 'x';\n",
        encoding="utf-8")
    assert [h.split(" ", 1)[0] for h in display_state_literals(tmp_path)] == ["a.ts:1", "a.ts:2"]


def test_the_import_check_sees_a_seeded_import(tmp_path):
    (tmp_path / "a.ts").write_text(
        "import { x } from '@/api/artifacts';\nimport { y } from './b';\n"
        "export { z } from '../types';\nconst m = await import('@/utils/x');\n", encoding="utf-8")
    assert [h.split(" ", 1)[0] for h in display_state_imports(tmp_path)] == ["a.ts:1", "a.ts:3", "a.ts:4"]


def read_banned(path: Path = BANNED) -> list[str]:
    """Lines are `build B | name`; `#` lines and blank lines are notes."""
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split(" | ", 1)
        assert len(parts) == 2 and parts[1].strip(), f"malformed banned-name line: {raw!r}"
        names.append(parts[1].strip())
    return names


def banned_hits(names: list[str], root: Path = FACET) -> list[str]:
    """Each place a banned name or file is found: the file itself, or a line that names it."""
    files = [n for n in names if n.endswith(SOURCE_SUFFIXES)]
    words = [n for n in names if n not in files]
    seen = [re.compile(rf"(?<![\w$]){re.escape(w)}(?![\w$])") for w in words]
    for f in files:
        # An import of the file: a quoted module path whose last part is the file's stem.
        stem = re.escape(Path(f).stem)
        seen.append(re.compile(rf"""['"/]{stem}(?:\.\w+)?['"]"""))
    hits = [f"{f} (the file)" for f in files if (root / f).exists()]
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            hits += [f"{rel}:{number} {line.strip()}" for p in seen if p.search(line)]
    return hits


def test_a_removed_name_does_not_come_back():
    hits = banned_hits(read_banned())
    assert not hits, (
        "These names were removed from the Facet and are banned (facet-banned-names.txt); the "
        "logic they held lives in an artifact:\n" + "\n".join(f"  {h}" for h in hits))


def test_the_banned_scan_sees_a_seeded_name(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "utils").mkdir()
    (tmp_path / "api" / "keys.ts").write_text("// KEY_MAX_DAYS was here\n", encoding="utf-8")
    (tmp_path / "utils" / "gone.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "Use.tsx").write_text(
        "import { x } from '@/utils/gone';\nconst KEY_MAX_DAYS_X = 2;\n", encoding="utf-8")
    hits = banned_hits(["KEY_MAX_DAYS", "utils/gone.ts"], tmp_path)
    assert hits == ["utils/gone.ts (the file)", "Use.tsx:1 import { x } from '@/utils/gone';",
                    "api/keys.ts:1 // KEY_MAX_DAYS was here"]
