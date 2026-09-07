# Contributing to Agience Chorus

The tekton standard library: operators by domain, each an independently-deployable service under
`src/<name>/` - aria, astra, iris, lumen, ophan, sage, seraph. **the hands** is an open gap.

## Tests

```bash
pip install ../agience-prism/py'[trust,vector,wire]' ../agience-crystal'[service,ontology]'             ../agience-mantle ../agience-ember
pip install -r requirements.txt
python -m pytest -q
```

Four siblings, all public, and none of them needs configuring: `crystal` is reached at 87 import
sites, `prism` at 73, `mantle` at 40, and `ember` at exactly one — `src/conftest.py`, a fixture
file. **Product code imports no ember**, and `src/tests/test_chorus_does_not_import_ember.py` holds
that.

The operator payloads need no environment variable either. They are this repository's own, in
`bundles/`, and `src/conftest.py` points `AGIENCE_BUNDLE_ROOT` at them before any test module
imports — without them several modules fail at import rather than at a test.

**After changing a tekton, rebuild the payloads.** The runtime reads the payload, not the source
file, so an unrebuilt edit is inert while everything still passes locally:

```bash
python ../agience-observe/build_bundles.py          # rebuild every group
python ../agience-observe/build_bundles.py --check  # report drift, write nothing
```

`src/tests/test_bundles_match_source.py` fails when they drift, and its companion corrupts a sha to
prove that check can actually fail.

## The three boundaries, all load-bearing

1. **Tektons never import one another.** Each constructs its own `AgienceServerAuth` and signs with
   its own identity. A cross-import is not a shortcut, it is a merge - and it silently makes two
   independently-deployable services one.
2. **Everything reaches Chorus over the wire** and never links it. Crystal is its own repo for
   exactly this reason.
3. **Tektons run model-free.** There is no LLM completion dispatch anywhere here. The fail-loud
   stubs - `invoke_llm`, `transcribe_artifact`, `resolve_llm_credentials` - raise
   `NotImplementedError` with the rule named in the tool description. **Do not implement one to make
   a test pass.**

`_shared/` is where a genuinely shared helper belongs; a second copy inside a tekton is how boundary
1 breaks by accident.

## The sub-apps

`src/astra/web/` and `src/aria/www/` are front-end trees with their own conventions, carried through
the restructure unedited - treat their instruction files as historical unless you check the path.

`src/astra/web/vendor/package/types` is vendored from `agience-crystal/src/types` and held
byte-identical by `agience-cloud/deploy/test_vendored_trees.py`. **Crystal's copy is canonical** -
edit there and re-sync; never edit the vendored side to make the check pass.

## Contributing

**Sign the CLA** - Chorus is AGPL-3.0-only **or** commercially licensed
([`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md)), so the project must hold the right to relicense
every line it ships. The bot checks on PR open and links [`CLA.md`](CLA.md).

Fork, branch from `main`, sign off every commit (`git commit -s`), open a PR. Commit format:
`fix:` / `feat(scope):` / `docs:` / `test:` / `chore:`.

**Security vulnerabilities: do not open a public issue** - email **connect@agience.ai**.

## License

**Dual-licensed: AGPL-3.0-only or commercial.** See [`LICENSE`](LICENSE),
[`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md) and [`NOTICE`](NOTICE). 
