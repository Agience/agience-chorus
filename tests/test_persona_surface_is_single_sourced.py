"""A persona's documented surface must match the one it registers.

Three artifacts describe every tekton's surface:

  * `<persona>/server.py`            — the `@mcp.tool` registrations. The truth.
  * `<persona>/.well-known/mcp.json` — what a client reads to discover the surface.
  * `<persona>/README.md`            — what a human reads.

The manifest and the README each restate what the server code already knows, and a hand-maintained
copy can drift from it: a tool can be documented as planned when it is live, listed as implemented
when it does not exist, or named differently in the manifest than in the code; environment variables
can be documented that no server reads while ones every server reads go unmentioned. None of that is
findable by reading a single document — each one can be internally coherent on its own — so this
test diffs every document against the code directly.

If this fails, regenerate the table from the code — do not hand-edit it back into agreement.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import textwrap

import pytest

PERSONAS = ("aria", "astra", "iris", "lumen", "ophan", "sage", "seraph")

# Read by the platform's own bootstrap, not by a persona server. Never expected in a persona manifest.
_NOT_PERSONA_ENV: set[str] = set()


def _src_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "src"


def _persona_dirs():
    root = _src_root()
    return [(p, root / p) for p in PERSONAS]


def _is_unconditional_stub(fn) -> bool:
    """True only when every path raises `NotImplementedError` — the raise sits at the top level of
    the body, after any docstring.

    A substring test on the whole function (`"NotImplementedError" in ast.dump(fn)`) would
    misclassify a live dispatcher that only raises on one branch — for example a function that
    raises for one `run.type` value and fully executes several others — as a placeholder, and a
    client filtering on that status would then skip a working tool. A raise nested in an `if` is a
    branch, not a contract.
    """
    body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    for stmt in body:
        if isinstance(stmt, ast.Raise) and "NotImplementedError" in ast.dump(stmt):
            return True
        if isinstance(stmt, (ast.Return, ast.If, ast.For, ast.While,
                             ast.With, ast.AsyncWith, ast.Try)):
            return False
    return False


def _registered(server_py: pathlib.Path) -> dict[str, bool]:
    """{tool_name: raises_not_implemented} for every `@mcp.tool` in the file."""
    tree = ast.parse(server_py.read_text(encoding="utf-8-sig", errors="replace"))
    out: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            dumped = ast.dump(dec)
            if "'mcp'" in dumped and "'tool'" in dumped:
                out[node.name] = _is_unconditional_stub(node)
                break
    return out


def _env_read(server_py: pathlib.Path) -> set[str]:
    src = server_py.read_text(encoding="utf-8-sig", errors="replace")
    # The pattern accepts digits and either quote style, and carries no minimum length: a narrower
    # class would make an env var invisible to this extractor on both the server side and the
    # manifest side.
    return (set(re.findall(r"""getenv\(\s*["']([A-Z][A-Z0-9_]*)["']""", src))
            | set(re.findall(r"""environ(?:\.get\(|\[)\s*["']([A-Z][A-Z0-9_]*)["']""", src))
            ) - _NOT_PERSONA_ENV


def _documented(readme: pathlib.Path) -> set[str]:
    """Tool names backticked inside markdown table rows. No length floor: a minimum length would
    silently skip short tool names such as `ask`."""
    names: set[str] = set()
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("|"):
            names |= set(re.findall(r"`([a-z][a-z0-9_]*)`", line))
    return names


def _runnable_blocks(readme: pathlib.Path) -> list[str]:
    """Fenced code blocks — the commands a reader is told to run.

    Extracted into its own function so the check and its control call the same implementation; a
    control that re-implements a copy of the regex can pass even when the real pattern silently
    reads prose instead of code.

    `[^\\n]*` after the tag so an info string carrying an attribute (```bash title="run.sh") or
    braces (```{python}) does not make the fences pair on the wrong delimiters.
    """
    return re.findall(r"```[a-zA-Z0-9_+-]*[^\n]*\n(.*?)```",
                      readme.read_text(encoding="utf-8", errors="replace"), flags=re.S)


def _claimed_tools(readme: pathlib.Path) -> set[str]:
    """Names a README table claims are tools — the first cell of each row, when that cell is nothing
    but a backticked lowercase identifier.

    Position is the signal. `_documented` scoops every backticked token in a row, which is right for
    "is this tool mentioned anywhere?" and useless for "does this row name a tool that does not
    exist?" — a description mentioning `workspace_id` would read as a phantom tool. Uppercase names
    are excluded, so config tables (`MANTLE_URI`) are not mistaken for tool rows.
    """
    names: set[str] = set()
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells:
            m = re.fullmatch(r"`([a-z][a-z0-9_]*)`", cells[0])
            if m:
                names.add(m.group(1))
    return names


@pytest.mark.parametrize("persona", PERSONAS)
def test_the_manifest_declares_exactly_the_registered_tools(persona):
    """A client discovers the surface here. A phantom name is a call that 404s; an omission is a
    capability nobody can find."""
    d = _src_root() / persona
    code = set(_registered(d / "server.py"))
    manifest = json.loads((d / ".well-known" / "mcp.json").read_text(encoding="utf-8"))
    declared = {t["name"] for t in manifest.get("tools", []) if isinstance(t, dict) and "name" in t}

    assert declared == code, (
        f"{persona}: manifest/code drift\n"
        f"  declared but NOT registered (phantom): {sorted(declared - code)}\n"
        f"  registered but NOT declared (hidden):  {sorted(code - declared)}"
    )


@pytest.mark.parametrize("persona", PERSONAS)
def test_the_manifest_env_is_exactly_what_the_server_reads(persona):
    d = _src_root() / persona
    reads = _env_read(d / "server.py")
    manifest = json.loads((d / ".well-known" / "mcp.json").read_text(encoding="utf-8"))
    env = manifest.get("config", {}).get("env", {})

    bookkeeping = [k for k in env if k.startswith("_")]
    assert not bookkeeping, (
        f"{persona}: {bookkeeping} sits inside config.env, where every other key is an environment "
        f"variable name. A consumer iterating this block reads it as a variable. Put notes at the "
        f"TOP LEVEL of the manifest instead."
    )
    assert set(env) == reads, (
        f"{persona}: manifest env/code drift\n"
        f"  declared but never read: {sorted(set(env) - reads)}\n"
        f"  read but not declared:   {sorted(reads - set(env))}"
    )


@pytest.mark.parametrize("persona", PERSONAS)
def test_the_readme_documents_every_registered_tool(persona):
    d = _src_root() / persona
    code = set(_registered(d / "server.py"))
    documented = _documented(d / "README.md")
    missing = sorted(code - documented)
    assert not missing, (
        f"{persona}: registered but absent from README tables: {missing}\n"
        f"Regenerate the table from the @mcp.tool registrations rather than adding rows by hand."
    )
    # The phantom direction — a README naming a tool the server does not register — needs its own
    # check: a one-directional "every registered tool is documented" check passes even when a
    # README lists a tool that was never implemented. `_documented` scoops every backticked
    # lowercase token in a table row, which would make a bare noun in a description a false
    # phantom, so the comparison uses `_claimed_tools`, which reads only the first cell of each row
    # — the position that actually names the tool — including single-token names like `ask` or
    # `search`, which a filter keyed on containing an underscore would miss.
    phantom = sorted(_claimed_tools(d / "README.md") - code)
    assert not phantom, (
        f"{persona}: README tables name tools the server does not register: {phantom}\n"
        f"Registered: {sorted(code)}"
    )


@pytest.mark.parametrize("persona", PERSONAS)
def test_the_manifest_status_matches_whether_the_tool_actually_stubs(persona):
    """Whether a tool actually stubs on every path must match its manifest status: a tool marked
    `status: not_implemented` while being a live dispatcher on some branch is a client-visible lie,
    since a client filtering on status drops a working tool. Reading `_is_unconditional_stub`'s
    result and then discarding it — collapsing to `set(...)` or `len(...)` before comparing — would
    let exactly that mismatch through undetected.
    """
    d = _src_root() / persona
    code = _registered(d / "server.py")            # {name: raises_on_every_path}
    manifest = json.loads((d / ".well-known" / "mcp.json").read_text(encoding="utf-8"))
    marked = {t["name"] for t in manifest.get("tools", [])
              if isinstance(t, dict) and t.get("status") == "not_implemented"}
    should = {n for n, stub in code.items() if stub}

    assert marked == should, (
        f"{persona}: manifest status/code mismatch\n"
        f"  marked not_implemented but LIVE (a client would skip a working tool): "
        f"{sorted(marked - should)}\n"
        f"  raises on every path but NOT marked: {sorted(should - marked)}"
    )


@pytest.mark.parametrize("persona", PERSONAS)
def test_no_runnable_command_sets_a_variable_the_server_never_reads(persona):
    """Every environment variable a README's runnable command sets must be one `server.py` actually
    reads. A documented variable the server never reads, or one the server needs left unmentioned,
    means a reader who follows the docs literally ends up with a persona wired to nothing."""
    d = _src_root() / persona
    reads = _env_read(d / "server.py")

    offenders = []
    # The fence pattern matches any language tag, not only `bash`/`sh`: a narrower alternation would
    # not match a ```json or ```python block, so a single non-bash fence in a README would pair the
    # fences on the wrong delimiters and this check would silently empty.
    for block in _runnable_blocks(d / "README.md"):
        for var in re.findall(r"\b([A-Z][A-Z0-9_]{3,})=", block):
            if var not in reads:
                offenders.append(var)
    assert not offenders, (
        f"{persona}: a runnable block sets {sorted(set(offenders))}, which server.py never reads. "
        f"It actually reads: {sorted(reads)}"
    )


def test_the_scan_actually_finds_tools_and_can_fail(tmp_path):
    """The control. Every assertion above compares two sets; if the extractors silently returned
    empty, all of them would pass on nothing. Prove each one sees real data, and that a seeded
    mismatch is caught."""
    counts = {p: len(_registered(d / "server.py")) for p, d in _persona_dirs()}
    assert all(n > 0 for n in counts.values()), f"a persona parsed to zero tools: {counts}"
    assert sum(counts.values()) > 50, f"implausibly few tools found overall: {counts}"

    # `_claimed_tools` is brittle by construction — it requires the first cell to be a bare
    # backticked identifier, so bolding a name or adding a status marker in that cell empties it.
    # Without a control, that emptiness would silently pass both the phantom check and the
    # run-command check, so this proves each extractor still sees real data across every persona.
    claimed = {p: len(_claimed_tools(d / "README.md")) for p, d in _persona_dirs()}
    assert all(n > 0 for n in claimed.values()), (
        f"_claimed_tools returned nothing for some persona: {claimed}. The phantom direction is "
        f"then vacuous. Did a tool table get reformatted (bold, status marker, extra cell)?"
    )
    assert sum(claimed.values()) >= sum(counts.values()), (
        f"fewer rows claimed than tools registered: {claimed} vs {counts}"
    )

    for persona, d in _persona_dirs():
        text = (d / "README.md").read_text(encoding="utf-8", errors="replace")
        blocks = _runnable_blocks(d / "README.md")
        assert blocks, f"{persona}: no fenced blocks found — the run-command check is vacuous"
        assert any("server.py" in b for b in blocks), (
            f"{persona}: the run block is not among the extracted fences. An info string carrying an "
            f"attribute (```bash title=\"run.sh\") or braces (```{{python}}) makes the fences pair on "
            f"the WRONG delimiters, and prose gets scanned instead of code."
        )

    for persona, d in _persona_dirs():
        assert _env_read(d / "server.py"), f"{persona}: env extractor found nothing"
        assert _documented(d / "README.md"), f"{persona}: README extractor found nothing"

    # a seeded phantom must be detected
    fake = tmp_path / "server.py"
    fake.write_text(
        "@mcp.tool(description='x')\n"
        "async def real_one():\n    return 1\n",
        encoding="utf-8",
    )
    got = _registered(fake)
    assert got == {"real_one": False}, got

    # A negative assertion against a fixture containing only one known name would prove nothing —
    # the dict is already pinned exactly by the assertion above it. The check below seeds a real
    # mismatch between the two shapes the stub classifier exists to tell apart.
    stub = tmp_path / "stub.py"
    stub.write_text(
        textwrap.dedent(
            """\
            @mcp.tool(description='x')
            async def all_paths_raise():
                raise NotImplementedError('no')

            @mcp.tool(description='y')
            async def one_branch_raises(mode):
                if mode == 'nope':
                    raise NotImplementedError('no')
                return 1
            """
        ),
        encoding="utf-8",
    )
    classified = _registered(stub)
    assert classified == {"all_paths_raise": True, "one_branch_raises": False}, (
        f"the stub classifier cannot tell a placeholder from a live dispatcher: {classified}. "
        f"A raise nested in an `if` is a branch, not a contract — that mistake published two working "
        f"tools as `status: not_implemented`."
    )
