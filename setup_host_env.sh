#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/venv"

echo "🐍 Python: $(python3 --version)"

# ------------------------------------------------------------
# 1. Create virtual environment if missing
# ------------------------------------------------------------
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "📦 Creating Python virtual environment at ${VENV_DIR} ..."
  python3 -m venv "${VENV_DIR}"
  echo "✅ Virtual environment created"
else
  echo "📦 Virtual environment already exists"
fi

# ------------------------------------------------------------
# 2. Activate virtual environment
# ------------------------------------------------------------
echo "🔧 Activating Python virtual environment..."
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# ------------------------------------------------------------
# 3. Upgrade core packaging tools
# ------------------------------------------------------------
echo "⬆️  Upgrading pip / setuptools / wheel..."
python -m pip install --upgrade pip setuptools wheel

# ------------------------------------------------------------
# 4. Install SeedCore (editable mode)
# ------------------------------------------------------------
echo "📚 Installing SeedCore in editable mode..."
pip install -e "${PROJECT_ROOT}"

# Optional: install extra requirements if present
if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
  echo "📦 Installing requirements.txt..."
  pip install -r "${PROJECT_ROOT}/requirements.txt"
fi

# ------------------------------------------------------------
# 5. Load host environment variables
# ------------------------------------------------------------
echo "🌍 Loading host environment variables..."
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/host/env.host"

# ------------------------------------------------------------
# 6. Start port forwarding
# ------------------------------------------------------------
echo "🚪 Starting port forwarding..."
"${PROJECT_ROOT}/deploy/port-forward.sh"

# ------------------------------------------------------------
# 7. Verify SeedCore architecture
# ------------------------------------------------------------
echo "🧠 Verifying SeedCore architecture..."
python "${PROJECT_ROOT}/scripts/host/verify_seedcore_architecture.py"

echo
echo "✅ Host setup and verification completed successfully!"


