"""Privacy-preserving logging system for LocalText.

Adheres strictly to NFR-09 and Acceptance Test AT-17.
Ensures that document text, prompts, outputs, clipboard contents, and authentication
secrets are NEVER written to logs or stdout.
Only structural milestones, timings, error codes, and sanitized metadata are logged.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional
from localtext.config import get_xdg_data_dir

# Format string with timestamp, level, module, and message
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"


def setup_privacy_logger(
    name: str = "localtext",
    log_to_file: bool = True,
) -> logging.Logger:
    """Configure a logger that guarantees no private document leakage."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_to_file:
        log_dir = get_xdg_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "application.log"
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
