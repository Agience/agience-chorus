# Operator code lives in chorus. Distributed to hosts as a content-addressed source bundle
# (definitions/build_bundles.py); ember executes it via ember/runner.py, sha-verified before
# exec. There are no code mirrors.
"""Local dev operators — the copilot's hands.

Each is an invokable operator artifact (same model as op.math.* / op.describe.*) that acts
on the local workspace: read, search, list, run tests, git, edit. Everything executes as a
local subprocess or filesystem call — no chorus, no network — so ember stays Apache-pure and
works fully offline. Paths are confined to the workspace root.

`op.dev.run_tests` is the gate: exit 0 = verified. That single operator is the flywheel's
verification rung — a code change is verified mass iff the suite it touches stays green,
exactly as `7*8==56` self-verifies arithmetic.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
         ".mypy_cache", ".pytest_cache", "target", "site-packages", ".continue"}
_TIMEOUT = 300

#: What identifies a genesis workspace root: it is the directory the sibling repos sit in. `agience-`
#: is the prefix every one of them carries, so the marker is a property of the checkout rather than
#: one repo's name — a workspace holding only `agience-ember`, or only `agience-chorus`, is still a
#: workspace, and none of them has to be the one this module was loaded from.
_MARKER = "agience-"

#: Resolved once and remembered. `None` means "not asked yet"; the answer itself is never None,
#: because failing to find a root RAISES rather than returning a root that does not exist.
_WORKSPACE: Optional[Path] = None


def _looks_like_workspace(d: Path) -> bool:
    try:
        return any(c.is_dir() and c.name.startswith(_MARKER) for c in d.iterdir())
    except OSError:
        return False


def _workspace() -> Path:
    """The workspace root every dev operator is confined to.

    No hard-coded checkout path in the fallback. This module is inlined verbatim into
    `agience-observe`'s content-addressed payloads and exec'd by `ember/runner.py` on other people's
    nodes, where such a directory does not exist: `.resolve()` on a POSIX host turns a Windows path
    into `<cwd>/c:/Users/…`, `_safe()` then confines every operator to a root nothing is under, and
    each one fails with "path escapes workspace" naming a path the operator was never given. A
    default that is wrong everywhere but one machine fails as a confusing error rather than as an
    instruction.

    Resolution order, and what each rung is for:

        CHORUS_WORKSPACE / EMBER_WORKSPACE   the host says. `EMBER_WORKSPACE` is still honoured so a
                                             host configured for the ember mirror behaves identically.
        the checkout this module was loaded from   `…/agience-chorus/src/lumen/dev_ops.py` — a
                                             developer importing `lumen.dev_ops` from a normal
                                             checkout needs to set nothing, which is the convenience
                                             the literal was providing. There is no `__file__` when
                                             the module arrives as bundle source, so this rung is
                                             skipped there rather than guessed at.
        upward from the working directory     the bundle case with no env var: a node running inside
                                             a checkout finds the root the same way `git` does.

    A root is only accepted if it actually looks like one — a directory holding `agience-*` repos —
    so a wrong `CHORUS_WORKSPACE` is refused at the point it is set rather than silently confining
    every operator to somewhere nothing exists.

    Raises `RuntimeError` naming the variable to set when no root can be found. Not at import: the
    bundle registers its operators at load, and refusing to load is not the same as refusing to run.
    """
    global _WORKSPACE
    if _WORKSPACE is not None:
        return _WORKSPACE

    said = os.getenv("CHORUS_WORKSPACE") or os.getenv("EMBER_WORKSPACE")
    if said:
        root = Path(said).expanduser().resolve()
        if not root.is_dir():
            raise RuntimeError(
                "CHORUS_WORKSPACE is set to %s, which is not a directory. It must name the folder "
                "the agience-* repos are checked out into." % root)
        _WORKSPACE = root
        return _WORKSPACE

    here = globals().get("__file__")
    if here:                                       # absent when this module arrives as bundle source
        for d in Path(here).resolve().parents:
            if _looks_like_workspace(d):
                _WORKSPACE = d
                return _WORKSPACE

    for d in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if _looks_like_workspace(d):
            _WORKSPACE = d
            return _WORKSPACE

    raise RuntimeError(
        "no agience workspace root found. Set CHORUS_WORKSPACE to the directory your agience-* "
        "repos are checked out into (the parent of agience-chorus), or run from inside it. "
        "Searched upward from %s." % Path.cwd())


def _safe(path: str) -> Path:
    """Resolve a path and confine it to the workspace (no escaping via .. or absolutes)."""
    workspace = _workspace()
    p = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if workspace not in p.parents and p != workspace:
        raise ValueError(f"path escapes workspace: {path}")
    return p


# ── read (safe) ───────────────────────────────────────────────────────────────
def _read_file(a: Dict) -> Dict:
    p = _safe(a["path"])
    text = p.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    start, end = int(a.get("start", 1)), a.get("end")
    end = int(end) if end is not None else len(lines)
    sliced = "\n".join(lines[start - 1:end])
    return {"path": p.as_posix(), "start": start, "end": end, "total_lines": len(lines), "content": sliced}


def _list_dir(a: Dict) -> Dict:
    p = _safe(a.get("path", "."))
    entries = sorted(f"{c.name}/" if c.is_dir() else c.name
                     for c in p.iterdir() if c.name not in _SKIP)
    return {"path": p.as_posix(), "entries": entries}


def _grep(a: Dict) -> Dict:
    pattern = re.compile(a["pattern"])
    root = _safe(a.get("path", "."))
    exts = set(a.get("exts", [".py", ".md", ".ts", ".js", ".json", ".toml", ".yaml", ".yml"]))
    limit = int(a.get("limit", 100))
    matches: List[Dict] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP]
        for fn in fns:
            if Path(fn).suffix.lower() not in exts:
                continue
            fp = Path(dp) / fn
            try:
                for i, line in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if pattern.search(line):
                        matches.append({"path": fp.as_posix(), "line": i, "text": line.strip()[:200]})
                        if len(matches) >= limit:
                            return {"pattern": a["pattern"], "matches": matches, "truncated": True}
            except Exception:
                continue
    return {"pattern": a["pattern"], "matches": matches, "truncated": False}


# ── verify — the gate (execute) ────────────────────────────────────────────────
def _run_tests(a: Dict) -> Dict:
    target = a.get("target", "")
    args = [sys.executable, "-m", "pytest", "-q"]
    if target:
        args.append(str(_safe(target)))
    env = dict(os.environ)
    # ember's `src` covers `ember.optics` (the instrument). A non-existent directory on PYTHONPATH is
    # silently ignored rather than an error, so this list is kept to paths that are genuinely
    # needed — and mantle's is not one of them. Its entry pointed INSIDE the package
    # (`agience-mantle/src/mantle`), which puts `db`, `shard` and `search` on the path as top-level
    # names and supplies no `mantle.*` at all; the `mantle.ontology` it named is gone from mantle
    # and its measures are chorus's own now (`src/corpus_stats.py`). mantle is a pip-installed
    # package, so it needs no path entry.
    env.setdefault("PYTHONPATH", str(_workspace() / "agience-ember" / "src"))
    try:
        r = subprocess.run(args, cwd=str(_workspace()), env=env, capture_output=True,
                           text=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"passed": False, "exit_code": -1, "summary": "TIMEOUT", "output": ""}
    tail = (r.stdout or "")[-1500:] + (r.stderr or "")[-500:]
    summary = next((ln for ln in reversed((r.stdout or "").splitlines())
                    if "passed" in ln or "failed" in ln or "error" in ln), "")
    return {"passed": r.returncode == 0, "exit_code": r.returncode, "summary": summary.strip(), "output": tail}


def _git(a: Dict) -> Dict:
    sub = a.get("subcommand", "status")
    allowed = {"status": ["status", "--short"], "diff": ["diff"], "log": ["log", "--oneline", "-20"],
               "show": ["show", "--stat"]}
    # `sub not in allowed` is checked explicitly rather than left to `allowed.get(sub, [...])`'s
    # default fallback: a silent fallback to `status` would run status but echo back the
    # caller's requested (unsupported) subcommand name, misreporting what actually ran.
    if sub not in allowed:
        return {"subcommand": sub, "output": "", "exit_code": 2, "ok": False,
                "error": "unsupported subcommand %r (allowed: %s)"
                         % (sub, ", ".join(sorted(allowed)))}
    cmd = ["git"] + allowed[sub]
    if a.get("path"):
        cmd.append(str(_safe(a["path"])))
    r = subprocess.run(cmd, cwd=str(_workspace()), capture_output=True, text=True, timeout=60)
    # stderr and exit_code are both surfaced here because `answer()` depends on them to detect a
    # git failure — a git failure with empty stdout (not a repo, bad object, index lock) would
    # otherwise read as a clean working tree.
    return {"subcommand": sub, "output": (r.stdout or "")[:4000], "exit_code": r.returncode,
            "ok": r.returncode == 0, "error": (r.stderr or "").strip()[:1000] or None}


# ── edit (write, deterministic) ────────────────────────────────────────────────
def _edit_file(a: Dict) -> Dict:
    p = _safe(a["path"])
    old, new = a["old"], a["new"]
    # An empty `old` would corrupt the whole file if let through: `"".count()` returns
    # len(text)+1, so the uniqueness guard below would see "many matches" and defer to
    # `replace_all`, and `text.replace("", new)` inserts `new` between every character:
    #     "def hello():".replace("", "X")  ->  "XdXeXfX XhXeXlXlXoX(X)X:"
    # reporting `{"applied": True, "replaced": len(text)+1}` as a successful edit. `invoke()`
    # passes the caller's dict straight through with no validation, and `_verify_change` reaches
    # this same function, so nothing upstream rejects it either — the guard below is the only one.
    if not isinstance(old, str) or old == "":
        return {"applied": False, "reason": "`old` must be a non-empty string "
                                            "(an empty match would rewrite every character)",
                "path": p.as_posix()}
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return {"applied": False, "reason": "old string not found", "path": p.as_posix()}
    if count > 1 and not a.get("replace_all"):
        return {"applied": False, "reason": f"old string not unique ({count} matches)", "path": p.as_posix()}
    p.write_text(text.replace(old, new), encoding="utf-8")
    return {"applied": True, "path": p.as_posix(), "replaced": count if a.get("replace_all") else 1}


def _restore(originals: Dict[str, str]) -> Dict:
    """Put every touched file back. Best-effort across all of them, and report what could not be.

    Both gates (`_verify_change`, `_rename_symbol`) call `_run_tests` inside a `try`, because
    `_run_tests` calls `_safe(target)`, which raises `ValueError` for a target outside the
    workspace, and `subprocess.run` can raise `OSError`/`TimeoutExpired`. A raise that skipped the
    revert would leave `_rename_symbol`'s already-rewritten files — every matching `.py` under
    `roots`, which defaults to the whole workspace, all 15 sibling repos — with no record of the
    prior contents anywhere, breaking the promise that a breaking change leaves the tree exactly
    as it was.

    A partial revert must also not be silent: if one write fails, the rest are still attempted and
    the failures are named, because a half-reverted workspace the operator does not know about is
    worse than either outcome."""
    failed = []
    for path, txt in originals.items():
        try:
            Path(path).write_text(txt, encoding="utf-8")
        except Exception as e:
            failed.append({"path": path, "error": "%s: %s" % (type(e).__name__, str(e)[:120])})
    return {"restored": len(originals) - len(failed), "restore_failed": failed}


def _verify_change(a: Dict) -> Dict:
    """The gate, mechanized: apply an edit, run the tests, keep it iff they stay green;
    otherwise revert and report the failure. This is the flywheel's verification rung —
    a change becomes verified mass only by passing reality (the suite), never by assertion.
    Self-protecting: a breaking change leaves the tree exactly as it was."""
    p = _safe(a["path"])
    target = a.get("target", "")
    original = p.read_text(encoding="utf-8")
    edited = _edit_file(a)
    if not edited.get("applied"):
        return {"accepted": False, "reason": edited.get("reason"), "reverted": False}
    # The suite may raise, not just fail — see `_restore`: without this `try`, an exception here
    # would skip the revert below and leave the edit applied.
    try:
        result = _run_tests({"target": target} if target else {})
    except Exception as e:
        r = _restore({p.as_posix(): original})
        return {"accepted": False, "reverted": True, "gate": "ERROR",
                "failure": "the test run itself raised: %s: %s" % (type(e).__name__, str(e)[:200]),
                **r}
    if result["passed"]:
        return {"accepted": True, "path": p.as_posix(), "gate": result["summary"]}
    p.write_text(original, encoding="utf-8")            # reject dark matter, restore reality
    return {"accepted": False, "reverted": True, "gate": result["summary"],
            "failure": result["output"][-600:]}


def _iter_files(root: Path, exts: set):
    """Yield workspace files under `root` (a file or a dir) with an allowed extension,
    skipping vendored/build dirs. Deterministic order per os.walk."""
    if root.is_file():
        if root.suffix.lower() in exts:
            yield root
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP]
        for fn in sorted(fns):
            if Path(fn).suffix.lower() in exts:
                yield Path(dp) / fn


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _rename_symbol(a: Dict) -> Dict:
    """Deterministic, gated refactor: replace the whole-word identifier `old` with `new`
    across the workspace (optionally scoped to `paths`), run the tests, and keep the rename
    iff they stay green — otherwise revert every touched file. A rename becomes verified mass
    only if reality (the suite) accepts it, exactly as `verify_change` gates a single edit.
    Whole-word (\\b) so `old` never matches inside a longer identifier or substring; the gate
    is the real safety net — a rename that breaks a call site fails the suite and is undone."""
    old, new = a["old"], a["new"]
    if not (_IDENT.fullmatch(old) and _IDENT.fullmatch(new)):
        return {"accepted": False, "reason": "old and new must be bare identifiers"}
    if old == new:
        return {"accepted": False, "reason": "old and new are identical"}
    exts = set(a.get("exts", [".py"]))
    target = a.get("target", "")
    roots = [_safe(p) for p in a["paths"]] if a.get("paths") else [_workspace()]
    pat = re.compile(rf"\b{re.escape(old)}\b")
    originals: Dict[str, str] = {}
    changed: List[Dict] = []
    for root in roots:
        for fp in _iter_files(root, exts):
            key = fp.as_posix()
            if key in originals:
                continue
            try:
                txt = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            hits = len(pat.findall(txt))
            if hits:
                originals[key] = txt
                fp.write_text(pat.sub(new, txt), encoding="utf-8")
                changed.append({"path": key, "count": hits})
    if not changed:
        return {"accepted": False, "reason": f"no whole-word occurrences of '{old}'", "files": 0}
    # The suite may raise, not just fail — and by this point every matching file under `roots`
    # (default: the entire workspace, all 15 sibling repos) has already been rewritten, with
    # `originals` the only copy of the prior contents. See `_restore`.
    try:
        result = _run_tests({"target": target} if target else {})
    except Exception as e:
        r = _restore(originals)
        return {"accepted": False, "reverted": True, "files": len(changed),
                "sites": sum(c["count"] for c in changed), "gate": "ERROR",
                "failure": "the test run itself raised: %s: %s" % (type(e).__name__, str(e)[:200]),
                **r}
    if result["passed"]:
        return {"accepted": True, "renamed": f"{old} -> {new}", "files": len(changed),
                "sites": sum(c["count"] for c in changed), "changed": changed[:50],
                "gate": result["summary"]}
    r = _restore(originals)                             # reject the refactor whole — restore reality
    return {"accepted": False, "reverted": True, "files": len(changed),
            "sites": sum(c["count"] for c in changed), "gate": result["summary"],
            "failure": result["output"][-600:], **r}


@dataclass(frozen=True)
class DevOp:
    name: str
    offer: str
    handler: Callable[[Dict], Dict]
    writes: bool = False


DEV_OPS: List[DevOp] = [
    DevOp("op.dev.read_file", "reads a file (optionally a line range) from the workspace", _read_file),
    DevOp("op.dev.list_dir", "lists a directory in the workspace", _list_dir),
    DevOp("op.dev.grep", "searches the workspace for a regex, returns file:line matches", _grep),
    DevOp("op.dev.run_tests", "runs the pytest suite (the verification GATE) — exit 0 = verified", _run_tests),
    DevOp("op.dev.git", "runs a read-only git command (status/diff/log/show) in the workspace", _git),
    DevOp("op.dev.edit_file", "applies a deterministic old->new edit to a file (unique match)", _edit_file, writes=True),
    DevOp("op.dev.verify_change", "applies an edit, runs the tests, keeps it iff green else reverts (the GATE)", _verify_change, writes=True),
    DevOp("op.dev.rename_symbol", "renames an identifier across the workspace (whole-word), runs the tests, keeps iff green else reverts ALL (the GATE)", _rename_symbol, writes=True),
]
_BY_NAME = {o.name: o for o in DEV_OPS}


# ADDED 2026-08-26. Operators were registered with NO `collection_id`, and the content seal keys
# on a collection origin root — so they could never be sealed and
# `data_integrity_check.artifacts_holding_inline_plaintext` climbed off zero on every boot. The
# repair that first drove that count to zero gave collectionless platform vocabulary `stage.system`
# "rather than an exemption"; the writers were never changed. This is that fix reaching the writer.
# `collection_id` alone suffices — `vertex._place` writes the origin containment edge from it, in
# the same savepoint as the row. Inlined, not shared: `_persona.load()` loads these modules
# individually and cross-importing between them is the hazard that module exists to prevent.
_SYSTEM_COLLECTION = "stage.system"


def _now_iso() -> str:
    """This observer's clock reading, claimed. The store never invents one (`vertex._attribute`
    returns untouched when `created_time` is None) and it is first-write-wins."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


#: Read ONCE per process, not per call. `manifest.OPERATORS = operators()` is computed at import
#: while `operators()` recomputes on demand, and `test_the_lumen_manifest_surface_is_unchanged_for_
#: the_host` asserts the two are equal — a fresh timestamp per call makes that impossible, and it
#: also makes the registered dict non-deterministic for anything that compares payloads. Reading
#: the clock at import gives one claim per process, which is what an idempotent upsert wants:
#: first-write-wins means only the first one is ever kept anyway.
_REGISTERED_AT = _now_iso()


def register_dev_operators(artifact_store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    n = 0
    for o in DEV_OPS:
        evolution.put_operator(artifact_store, {
            "id": o.name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": o.offer, "content": f"dev operator {o.name}: {o.offer}"
            + ("  [WRITES]" if o.writes else "  [read-only]"), "created_by": author,
            "collection_id": _SYSTEM_COLLECTION, "created_time": _REGISTERED_AT,
        })
        n += 1
    return n


def invoke(name: str, arguments: Optional[Dict] = None) -> Dict:
    """Run a dev operator by name (the InvokeArtifactRequest analogue: name + arguments)."""
    o = _BY_NAME.get(name)
    if o is None:
        raise KeyError(f"no dev operator '{name}'")
    return o.handler(arguments or {})


# ── deterministic action routing (NL intent -> operator) ───────────────────────
# Only safe ops are routable from chat; edit_file stays explicit-invoke (never NL-triggered).
# (extracted from ember engine.py) — loaded two ways; see the note on the same import in
# `lumen/arithmetic.py`. Relative resolves the bundle sibling (`<pkg>.answer`); bare resolves under the
# persona-load convention (persona dir on `sys.path`). Bare-only silently un-bundles this organon.
try:
    from .answer import Answer      # noqa: E402  bundle / package context
except ImportError:                 # noqa: E402  pragma: no cover - persona-load context
    from answer import Answer       # noqa: E402  bare-name context

_RUN = re.compile(r"\brun (?:the )?tests?\b|\brun pytest\b|\bcheck (?:the )?tests?\b")
_GIT = re.compile(r"\bgit (status|diff|log)\b|\bwhat(?:'s| has) changed\b|\bshow (?:me )?the diff\b")
_GREP = re.compile(r"\b(?:grep|search(?: for)?|find)\b\s+[`'\"]?(.+?)[`'\"]?\s+in (?:the )?(?:code|repo|codebase|source)")
_READ = re.compile(r"\b(?:read|show|open|cat|display)\b(?:\s+me)?(?:\s+the)?(?:\s+file)?\s+[`'\"]?([\w./\\-]+\.\w+)")
_LS = re.compile(r"\b(?:list|ls)\b(?:\s+the)?(?:\s+files?)?(?:\s+in)?\s+[`'\"]?([\w./\\-]+)")


def looks_dev_action(query: str) -> bool:
    q = query.lower()
    return any(p.search(q) for p in (_RUN, _GIT, _GREP, _READ, _LS))


def answer(query: str) -> Optional[Answer]:
    q = query.lower()
    if _RUN.search(q):
        r = invoke("op.dev.run_tests", {"target": _first_path(query) or "agience-ember"})
        verdict = "✓ PASS" if r["passed"] else "✗ FAIL"
        return _ans(f"{verdict} — {r['summary'] or 'ran tests'}\n\n{r['output'][-800:]}",
                    "op.dev.run_tests", r["passed"])
    m = _GIT.search(q)
    if m:
        sub = (m.group(1) if m.lastindex and m.group(1) else ("diff" if "diff" in q else "status"))
        r = invoke("op.dev.git", {"subcommand": sub})
        # `ok`/`exit_code` are checked explicitly: rendering `output or "(clean / no output)"`
        # unconditionally would read a git failure with empty stdout as a clean working tree.
        if not r.get("ok", r.get("exit_code") == 0):
            return _ans(f"git {sub} failed (exit {r.get('exit_code')}): "
                        f"{r.get('error') or 'no stderr'}", "op.dev.git", False)
        return _ans(f"git {sub}:\n{r['output'] or '(clean / no output)'}", "op.dev.git", True)
    m = _GREP.search(q)
    if m:
        r = invoke("op.dev.grep", {"pattern": re.escape(m.group(1).strip())})
        hits = "\n".join(f"- {h['path']}:{h['line']}  {h['text']}" for h in r["matches"][:20])
        return _ans(f"{len(r['matches'])} match(es) for '{m.group(1).strip()}':\n{hits}"
                    or "no matches", "op.dev.grep", bool(r["matches"]))
    m = _READ.search(query)
    if m:
        try:
            r = invoke("op.dev.read_file", {"path": m.group(1)})
        except (FileNotFoundError, ValueError):
            return None
        return _ans(f"{r['path']} ({r['total_lines']} lines):\n{r['content'][:1500]}", "op.dev.read_file", True)
    m = _LS.search(query)
    if m:
        try:
            r = invoke("op.dev.list_dir", {"path": m.group(1)})
        except (FileNotFoundError, ValueError):
            return None
        return _ans(f"{r['path']}:\n  " + "  ".join(r["entries"][:60]), "op.dev.list_dir", True)
    return None


def _first_path(q: str) -> Optional[str]:
    m = re.search(r"[`'\"]?([\w./\\-]+\.\w+|[\w./\\-]+/)[`'\"]?", q)
    return m.group(1) if m else None


def _ans(text: str, op: str, ok: bool) -> Answer:
    return Answer(text=text, grounded=ok, cited=[op], read={"engine": "dev", "operator": op, "ok": ok})
