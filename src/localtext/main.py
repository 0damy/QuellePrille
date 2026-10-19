"""LocalText application entry point.

Launches the native Qt desktop GUI if PySide6 is installed, or the interactive
command-line tool if invoked with arguments or when running in headless mode.
"""

from __future__ import annotations

import sys


def launch_gui() -> int:
    """Launch the PySide6 / Qt6 desktop window."""
    try:
        from PySide6.QtWidgets import QApplication
        from localtext.gui.main_window import create_qt_app

        app = QApplication(sys.argv)
        app.setApplicationName("LocalText")
        window = create_qt_app()
        window.show()
        return app.exec()
    except ImportError as exc:
        print(f"Cannot start the GUI: {exc}. Run scripts/setup_env.sh.", file=sys.stderr)
        return 1


def main() -> None:
    # If command-line arguments are provided, route to CLI
    if len(sys.argv) > 1 and sys.argv[1] not in {"--gui", "-g"}:
        from localtext.cli import main as cli_main
        cli_main()
    else:
        raise SystemExit(launch_gui())


if __name__ == "__main__":
    main()

