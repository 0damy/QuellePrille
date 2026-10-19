"""LocalText configuration, XDG directory paths, and runtime constants.

Adheres strictly to NFR-02, NFR-03, NFR-06, and APP-09.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# --- Limits ---
MAX_DISPLAYED_WORDS = 10_000
MAX_INPUT_BYTES = 1_048_576  # 1 MiB UTF-8 input (APP-09)
DETECTOR_MIN_PROSE_WORDS = 150  # DET-03

# Memory admission guardrail (NFR-06): minimum required OS headroom in bytes
MIN_OS_HEADROOM_BYTES = 6 * 1024 * 1024 * 1024  # 6.0 GiB


def _ensure_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        # If filesystem is read-only (e.g. sandbox or restricted container), fall back to /tmp
        fallback = Path(f"/tmp/localtext_{path.name}")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_xdg_config_dir() -> Path:
    """Return XDG_CONFIG_HOME/localtext directory."""
    base = os.environ.get("XDG_CONFIG_HOME")
    path = Path(base) if base else Path.home() / ".config"
    return _ensure_dir(path / "localtext")


def get_xdg_data_dir() -> Path:
    """Return XDG_DATA_HOME/localtext directory."""
    base = os.environ.get("XDG_DATA_HOME")
    path = Path(base) if base else Path.home() / ".local" / "share"
    return _ensure_dir(path / "localtext")


def get_xdg_cache_dir() -> Path:
    """Return XDG_CACHE_HOME/localtext directory."""
    base = os.environ.get("XDG_CACHE_HOME")
    path = Path(base) if base else Path.home() / ".cache"
    return _ensure_dir(path / "localtext")


def get_models_dir() -> Path:
    """Directory where downloaded or imported local model weights reside."""
    models_dir = get_xdg_data_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_private_runtime_dir() -> Path:
    """Return a private directory (permission 0700) for runtime secrets and sockets (NFR-02, NFR-03)."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and Path(base).exists():
        runtime_dir = Path(base) / "localtext"
    else:
        # Fallback to user-isolated tmp directory with restricted permissions
        uid = os.getuid()
        runtime_dir = Path(f"/tmp/localtext-runtime-{uid}")

    runtime_dir.mkdir(parents=True, exist_ok=True)
    # Ensure mode 0700 (owner-only read/write/execute)
    os.chmod(runtime_dir, stat.S_IRWXU)
    return runtime_dir
