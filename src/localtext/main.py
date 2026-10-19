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
    except ImportError:
        print(
            "PySide6 is not installed in the current environment.\n"
            "To launch the graphical desktop interface, install PySide6 or use the system package 'pyside6'.\n"
            "Falling back to the LocalText CLI tool.\n",
            file=sys.stderr,
        )
        from localtext.cli import main as cli_main
        cli_main()
        return 0


def main() -> None:
    # If command-line arguments are provided, route to CLI
    if len(sys.argv) > 1 and sys.argv[1] not in {"--gui", "-g"}:
        from localtext.cli import main as cli_main
        cli_main()
    else:
        launch_gui()


if __name__ == "__main__":
    main()
