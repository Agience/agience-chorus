# Contributing to Agience Chorus

## Build and test

```bash
pip install -r requirements.txt
python -m pytest -q
```

Chorus runs from a checkout: no directory under `src/` carries an `__init__.py`. Tektons never
import one another, and each builds its own server auth.

**The runtime reads the bundle payload, not the source file.** After changing a tekton, rebuild the
bundles or the change is inert — `src/tests/test_bundles_match_source.py` fails when they drift.

## Contributing

Fork, branch from `main`, sign off every commit (`git commit -s`) to certify the
[DCO](https://developercertificate.org/), open a PR. Commit format: `fix:` · `feat(scope):` ·
`docs:` · `test:` · `chore:`.

**Sign the CLA.** This project is AGPL-3.0-only **or** commercially licensed
([`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md)), so the project must hold the right to relicense
every line it ships. The bot checks on PR open and links [`CLA.md`](CLA.md).

Dual-licensed — see [`LICENSE`](LICENSE), [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md),
[`NOTICE`](NOTICE) and [`CLA.md`](CLA.md).
