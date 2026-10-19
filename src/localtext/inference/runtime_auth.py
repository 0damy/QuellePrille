"""Local inference runtime secret management and loopback authentication.

Adheres strictly to NFR-03 and Acceptance Test AT-02.
Generates an ephemeral cryptographic secret stored in a mode 0600 file within
the private runtime directory. Secrets are never exposed on command line arguments
or logs.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from localtext.config import get_private_runtime_dir


class RuntimeAuthManager:
    """Manages ephemeral API secrets for the local llama-server child process."""

    def __init__(self, key_filename: str = "llama_api_key.txt"):
        self.runtime_dir = get_private_runtime_dir()
        self.key_file_path = self.runtime_dir / key_filename
        self._secret: str = ""

    def generate_secret(self) -> str:
        """Generate a cryptographically secure random secret and write to a private file (mode 0600)."""
        self._secret = secrets.token_urlsafe(32)

        # Write to temporary file with restrictive permissions (0600)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = stat.S_IRUSR | stat.S_IWUSR  # 0600 (read/write only by owner)

        fd = os.open(str(self.key_file_path), flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self._secret.strip() + "\n")

        # Double check file permission
        os.chmod(self.key_file_path, stat.S_IRUSR | stat.S_IWUSR)
        return self._secret

    @property
    def secret(self) -> str:
        if not self._secret and self.key_file_path.exists():
            self._secret = self.key_file_path.read_text(encoding="utf-8").strip()
        return self._secret

    def get_auth_headers(self) -> dict[str, str]:
        """Headers required for authenticating loopback requests to llama-server."""
        return {
            "Authorization": f"Bearer {self.secret}",
            "Content-Type": "application/json",
        }

    def cleanup(self) -> None:
        """Securely wipe the secret file upon shutdown."""
        if self.key_file_path.exists():
            try:
                # Overwrite before deleting
                length = self.key_file_path.stat().st_size
                with open(self.key_file_path, "wb") as f:
                    f.write(b"\x00" * max(length, 64))
                self.key_file_path.unlink()
            except OSError:
                pass
        self._secret = ""
