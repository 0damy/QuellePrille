"""Session manager: explicit session saving, clearing, and privacy guarantees.

Adheres strictly to APP-07 and Acceptance Test AT-18.
Defaults to zero persisted document history. Document text remains strictly in RAM
unless the user explicitly commands a session save.
Provides one-click session clearing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from localtext.config import get_xdg_data_dir


@dataclass
class SavedSession:
    text: str
    language: str
    active_mode: str
    model_profile_id: str
    timestamp: str


class SessionManager:
    """Handles explicit session saving and clearing under XDG data directory."""

    def __init__(self, session_filename: str = "last_session.json"):
        self.session_file = get_xdg_data_dir() / session_filename

    def has_saved_session(self) -> bool:
        return self.session_file.exists()

    def save_session(
        self,
        text: str,
        language: str = "en",
        active_mode: str = "standard",
        model_profile_id: str = "qwen-9b-q6k",
    ) -> None:
        """Explicitly save the active session (APP-07, AT-18)."""
        import datetime
        data = {
            "text": text,
            "language": language,
            "active_mode": active_mode,
            "model_profile_id": model_profile_id,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self.session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_session(self) -> Optional[SavedSession]:
        """Restore explicitly saved session state."""
        if not self.has_saved_session():
            return None
        try:
            raw = json.loads(self.session_file.read_text(encoding="utf-8"))
            return SavedSession(
                text=raw.get("text", ""),
                language=raw.get("language", "en"),
                active_mode=raw.get("active_mode", "standard"),
                model_profile_id=raw.get("model_profile_id", "qwen-9b-q6k"),
                timestamp=raw.get("timestamp", ""),
            )
        except Exception:
            return None

    def clear_session(self) -> None:
        """Securely remove any saved session data (APP-07)."""
        if self.session_file.exists():
            try:
                # Overwrite before unlink
                size = self.session_file.stat().st_size
                with open(self.session_file, "wb") as f:
                    f.write(b"\x00" * max(size, 64))
                self.session_file.unlink()
            except OSError:
                pass
