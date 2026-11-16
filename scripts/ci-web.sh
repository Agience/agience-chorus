#!/usr/bin/env bash
# The web app's CI, as one command: GitHub's `web` job (ci.yml) and node 45's gate both run this,
# so what passes on node 45 is what GitHub runs.
#
#   bash scripts/ci-web.sh <app>      # e.g. src/agience_chorus/astra/web
#
# The Node major the workflow names, a clean install from the lockfile, the production build, the
# app's tests where it has a suite, then lint with no warnings allowed.
set -euo pipefail
cd "$(dirname "$0")/.."
app="${1:?usage: scripts/ci-web.sh <app>}"
# The Node the workflow names (setup-node's node-version), here too: another major is refused.
want=$(sed -n 's/^ *node-version: *"\{0,1\}\([0-9][0-9]*\).*/\1/p' .github/workflows/ci.yml | head -1)
[ -n "$want" ] || { echo "ci-web: the workflow names no node-version" >&2; exit 1; }
have=$(node -p "process.versions.node.split('.')[0]")
[ "$want" = "$have" ] || { echo "ci-web: Node $have here, the workflow runs Node $want" >&2; exit 1; }
npm ci --prefix "$app"
npm run build --prefix "$app"
if node -e "process.exit(require('./$app/package.json').scripts.test?0:1)"; then
  npm run test --prefix "$app"
else
  echo "no test script in $app: build and lint are the signal"
fi
npm run lint --prefix "$app"
echo "ci-web: $app passed"
