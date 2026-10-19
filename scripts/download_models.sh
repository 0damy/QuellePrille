#!/usr/bin/env bash
# Explicit online acquisition. Runtime loading never downloads missing files.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    echo "First run: bash scripts/setup_env.sh --detector" >&2
    exit 1
fi
exec "${PROJECT_ROOT}/.venv/bin/python" "${SCRIPT_DIR}/download_detector.py" "$@"
