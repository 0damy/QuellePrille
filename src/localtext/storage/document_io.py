"""Document file import, export, and atomic save operations.

Adheres strictly to APP-02 and NFR-10.
Supports UTF-8 TXT and Markdown files.
Performs atomic writes via temporary files and os.replace to prevent corruption on crash.
Never overwrites existing files without explicit confirmation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Tuple


class DocumentIOError(IOError):
    """Raised on file import, export, or permission failures."""
    pass


class DocumentIO:
    """Handles safe, atomic disk I/O for text and markdown documents."""

    @staticmethod
    def read_file(file_path: Path) -> Tuple[str, str]:
        """Read a TXT or Markdown file. Returns (content, detected_format)."""
        if not file_path.exists():
            raise DocumentIOError(f"File not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix not in {".txt", ".md", ".markdown"}:
            raise DocumentIOError(
                f"Unsupported file format '{suffix}'. Supported formats: .txt, .md."
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = file_path.read_text(encoding="utf-8-sig")
            except Exception as e:
                raise DocumentIOError(f"Failed to read '{file_path}' as UTF-8: {e}")

        fmt = "markdown" if suffix in {".md", ".markdown"} else "text"
        return content, fmt

    @staticmethod
    def atomic_save(
        file_path: Path,
        content: str,
        allow_overwrite: bool = False,
    ) -> None:
        """Atomically write text to disk using a temporary file and atomic rename (NFR-10)."""
        target = file_path.resolve()

        if target.exists() and not allow_overwrite:
            raise DocumentIOError(
                f"File '{target}' already exists. Explicit confirmation required to overwrite (NFR-10)."
            )

        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file in the same filesystem directory to ensure atomic rename
        temp_fd, temp_path_str = tempfile.mkstemp(
            prefix=".localtext_save_", dir=str(parent), text=True
        )
        temp_path = Path(temp_path_str)

        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename (replaces destination atomically on POSIX)
            temp_path.replace(target)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise DocumentIOError(f"Atomic save failed for '{target}': {e}")
