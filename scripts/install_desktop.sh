#!/usr/bin/env bash
# Install user-level .desktop file for LocalText (APP-01)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DESKTOP_DIR="${HOME}/.local/share/applications"
mkdir -p "${DESKTOP_DIR}"

cat <<EOF > "${DESKTOP_DIR}/localtext.desktop"
[Desktop Entry]
Name=LocalText
Comment=Private AI Text Detection and Rephrasing
Exec=${PROJECT_ROOT}/scripts/run_app.sh
Terminal=false
Type=Application
Categories=Office;Utility;TextEditor;
Keywords=Text;AI;Detection;Paraphrase;Rephrase;
EOF

chmod +x "${DESKTOP_DIR}/localtext.desktop"
echo "✓ Installed user-level desktop entry at: ${DESKTOP_DIR}/localtext.desktop"
echo "LocalText will now appear in your application launcher."

