#!/usr/bin/env bash
# Fixture-backed Q2 gates: queue/detail/replay/runbook TypeScript contracts + parsers.
# Does not start HTTP servers; uses tsx tests under ts/tests/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}/ts"
npm run typecheck
npm test
echo "Q2 verification contract checks passed."
