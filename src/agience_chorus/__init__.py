"""Chorus — the Agience tool surface: seven tektons, each independently deployable.

Crystal routes, ember runs, chorus is the tool surface. Each tekton constructs its own server auth,
signs with its own identity, and imports no sibling tekton.

The import name is `agience_chorus`, QUALIFIED — it says whose it is. An unqualified `chorus` would
claim a common word in the global import namespace, which is how a package ends up shadowing, or
shadowed by, something unrelated: this repository hit exactly that during the packaging work, when
an `agience` package belonging to another project made `agience.chorus` unresolvable.

Each tekton is a subpackage: `agience_chorus.aria`, `.sage`, `.astra`, `.lumen`, `.iris`,
`.ophan`, `.seraph`.
"""

# ── where this installation's operator payloads are ──────────────────────────────────────────────
# The runtime executes the PAYLOAD, never the source file, and `prism.runner` deliberately performs
# no in-package lookup of its own: a silent fallback to an embedded copy is how two versions of a
# content-addressed payload start to disagree, and the sha gate would then verify the wrong bytes
# faithfully. Its docstring names the correct route instead — "a host binds its own payloads".
#
# Chorus is that host, and this is it binding them: an explicit statement of where ITS payloads sit,
# not a guess derived from a file's location. Without it, `pip install agience-chorus` followed by
# `python -m agience_chorus.server` starts every tekton and loads NO manifest — "no bundle for group
# 'web_bff'", six times — which reads as a broken install rather than an unset variable.
#
# `setdefault`, so it changes nothing for a deployment that names its own root, and the store still
# takes precedence over files either way. Set here, in the package's `__init__`, because
# `prism.runner` reads the variable once at import and any submodule may import it first.
import os as _os
from pathlib import Path as _Path

_os.environ.setdefault("AGIENCE_BUNDLE_ROOT", str(_Path(__file__).resolve().parent / "bundles"))

del _os, _Path
