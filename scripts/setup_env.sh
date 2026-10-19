#!/usr/bin/env bash
# Native GUI setup; detector dependencies are an explicit optional install.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ "${1:-}" != "" && "${1:-}" != "--detector" ]]; then
    echo "Usage: bash scripts/setup_env.sh [--detector]" >&2
    exit 2
fi
if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    "${LOCALTEXT_PYTHON:-python3}" -m venv --system-site-packages "${PROJECT_ROOT}/.venv"
fi
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
"${VENV_PYTHON}" -m pip install -e "${PROJECT_ROOT}[gui]"
if [[ "${1:-}" == "--detector" ]]; then
    # Avoid pulling NVIDIA libraries on the Intel/CPU target.
    if ! "${VENV_PYTHON}" -c 'import torch' 2>/dev/null; then
        "${VENV_PYTHON}" -m pip install 'torch>=2.6,<3' --index-url https://download.pytorch.org/whl/cpu
    fi
    "${VENV_PYTHON}" -m pip install -e "${PROJECT_ROOT}[detector]"
fi
"${VENV_PYTHON}" -c 'import PySide6, requests, psutil, localtext.main'
echo "Setup complete. Start with: bash scripts/run_app.sh"
