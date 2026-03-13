#!/usr/bin/env bash

set -euo pipefail

echo "=========================================="
echo "SeedCore PDP Boundary Verification Script"
echo "=========================================="
echo ""
echo "This script executes the deterministic policy evaluation rules"
echo "and verifies the exact allow/deny constraints defined in:"
echo "docs/development/policy_gate_matrix.md"
echo ""

if [ ! -d ".venv" ] && [ ! -d "venv" ]; then
    echo "Error: Python virtual environment not found in repository root."
    echo "Run this script from the root of the seedcore repository."
    exit 1
fi

VENV_BIN=".venv/bin"
if [ ! -d "$VENV_BIN" ]; then
    VENV_BIN="venv/bin"
fi

if [ ! -f "$VENV_BIN/pytest" ]; then
    # Fallback to system pytest or just pytest in path
    PYTEST_CMD="pytest"
else
    PYTEST_CMD="$VENV_BIN/pytest"
fi

echo "--- RUNNING POLICY MATRIX TESTS ---"
echo "Targeting deterministic boundaries in test_action_intent.py"
$PYTEST_CMD -v tests/test_action_intent.py

echo ""
echo "--- RUNNING GOVERNED CLOSURE TESTS ---"
echo "Targeting final execution and evidence generation"
$PYTEST_CMD -v tests/test_governed_closure.py tests/test_evidence_bundle.py

echo ""
echo "=========================================="
echo "✅ PDP Boundary explicit conditions verified."
echo "✅ Execution tokens generated deterministically."
echo "✅ No LLM involvement in synchronous policy enforcement."
echo "=========================================="