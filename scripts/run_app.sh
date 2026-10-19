#!/usr/bin/env bash
# LocalText Application Launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"

if [ ! -d "${PROJECT_ROOT}/.venv" ]; then
    echo "Virtual environment not found. Running setup..."
    "${SCRIPT_DIR}/setup_env.sh"
fi

exec "${PROJECT_ROOT}/.venv/bin/python" -m localtext.main "$@"

