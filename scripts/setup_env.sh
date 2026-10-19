#!/usr/bin/env bash
# LocalText Environment Setup Script for Arch Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Setting up LocalText environment on Arch Linux ==="

# 1. Check for system PySide6 or advise installation
if ! pacman -Q pyside6 &>/dev/null; then
    echo "Notice: Arch system package 'pyside6' is not yet installed."
    echo "For the native Qt desktop GUI, run:"
    echo "    sudo pacman -S pyside6"
    echo ""
fi

# 2. Create isolated venv inheriting system packages if not already present
if [ ! -d "${PROJECT_ROOT}/.venv" ]; then
    echo "Creating virtual environment at .venv (inheriting system-tested packages)..."
    python3 -m venv --system-site-packages "${PROJECT_ROOT}/.venv"
fi

# 3. Verify PySide6 in .venv
if "${PROJECT_ROOT}/.venv/bin/python" -c "import PySide6" 2>/dev/null; then
    echo "✓ PySide6 is available for the desktop GUI."
else
    echo "! PySide6 is not detected inside .venv."
    echo "  You can install it either via system pacman:"
    echo "      sudo pacman -S pyside6"
    echo "  Or into .venv directly:"
    echo "      ${PROJECT_ROOT}/.venv/bin/pip install PySide6"
fi

echo "=== Setup check complete ==="
