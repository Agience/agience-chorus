"""An INSTALLED aria, with no `www/` beside it, must refuse the way a bundled one does.

`test_manifest_is_a_bundle_aria.py` covers the bundle: exec'd from distributed text, `__file__` is
undefined, `_bff_main_path()` answers `None`, and `bff_app()` raises a `RuntimeError` naming the
seam and the call that binds it. This is that test's sibling, and it was the untested half.

⛔ AN INSTALLED COPY HAS A `__file__` AND STILL HAS NO `www/`. The directory does not travel:
`packages.find.exclude` names `*.www*` and no `package-data` pattern covers it. Measured 2026-09-16
against a freshly built wheel, which carries **0** entries under `aria/www/` — so every `pip install`
of chorus is in exactly this state.

⚠ The evidence is the wheel, not `build/lib`. That directory agrees, and it is not proof of
anything: setuptools stages into it and reuses what is already there, so it describes the last build
rather than the current source. `tests/test_the_built_wheel_carries_the_runtime_data.py` was written
after that caught me — its first version built in the checkout and passed its own negative case.

⛔ AND THE DESIGNED MESSAGE DID NOT FIRE THERE. `_bff_main_path()` only answered `None` for the
bundle case, so an installed copy got a path to a file that was not there and `exec_module` raised a
bare `FileNotFoundError`. The careful RuntimeError — the one that says *bind the seam, here is the
call* — was unreachable in the commoner of the two ways the file can be absent.

⚠ THE MESSAGE IS THE WHOLE DIAGNOSIS, WHICH IS WHY ITS TEXT IS ASSERTED. `personas.py` mounts this
facet inside `except Exception: log.warning("Aria web facet not loaded: %s", exc)` — deliberately,
so a missing facet cannot unmount the persona. The node then boots, answers `/healthz`, serves
`/aria/mcp`, and simply has no `/aria/chat`. One log line is the entire signal, and
`[Errno 2] No such file or directory` does not tell an operator what to do about it.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_WEB_BFF = Path(__file__).resolve().parents[1] / "web_bff.py"


def _load_copy_without_www(tmp_path: Path):
    """Import `web_bff.py` from a directory that has no `www/` beside it.

    A copy rather than the real module: the point is a real `__file__` with nothing next to it,
    which is what an installed package looks like and what the in-tree module can never be.
    """
    target = tmp_path / "web_bff.py"
    shutil.copyfile(_WEB_BFF, target)
    spec = importlib.util.spec_from_file_location("aria_web_bff_installed_copy", target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:                                    # pragma: no cover - import-time failure
        sys.modules.pop(spec.name, None)
        raise
    return mod


@pytest.fixture
def installed(tmp_path):
    mod = _load_copy_without_www(tmp_path)
    # `bff_app()` short-circuits on this cache, and the real module may have populated it.
    sys.modules.pop(mod._BFF_MODULE_NAME, None)
    yield mod
    sys.modules.pop("aria_web_bff_installed_copy", None)
    sys.modules.pop(mod._BFF_MODULE_NAME, None)


def test_the_copy_really_has_a_file_and_really_has_no_www(installed, tmp_path):
    """Both halves of the premise. Without the first this is just the bundle case again; without
    the second the module would load the app and every assertion below would be vacuous."""
    assert installed.__file__ is not None, "the copy has no __file__, so this is the bundle case"
    assert not (tmp_path / "www").exists(), "the fixture directory unexpectedly has a www/ tree"


def test_an_absent_file_is_reported_as_absent(installed):
    """`None`, not a path to something that is not there.

    The docstring's own words are "Absence is reported as absence" — it just did not cover this
    way of being absent.
    """
    assert installed._bff_main_path() is None


def test_serving_is_refused_with_the_message_that_names_the_fix(installed):
    with pytest.raises(RuntimeError) as exc:
        installed.bff_app()

    message = str(exc.value)
    assert installed.BFF_MAIN_SEAM in message, (
        "the refusal does not name the seam, so an operator cannot act on it: %s" % message)
    assert "register_seam" in message, (
        "the refusal does not name the call that binds the seam: %s" % message)


def test_registration_still_works_without_the_facet(installed):
    """The two are independent and must stay so.

    Registration needs only the payload; serving needs the file. Coupling them would mean a node
    that cannot serve the chat page also stops advertising the operator it genuinely has.
    """
    captured = []

    class _Store:
        def put_artifact(self, artifact):
            captured.append(artifact["id"])
            return artifact

        def get_artifact(self, artifact_id):
            return None

    assert installed.register_web_operators(_Store()) > 0
    assert captured, "nothing was written, so registration did not actually run"
