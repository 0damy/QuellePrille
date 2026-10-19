"""Managed child process supervisor for local inference servers.

Adheres strictly to Section 6, NFR-01, NFR-03, NFR-07, and Acceptance Test AT-10.
- Binds strictly to numeric loopback 127.0.0.1.
- Authenticates using private mode 0600 secret file via --api-key-file.
- Disables prompt and document text logging.
- Manages process lifecycle: start, health check, responsive cancellation, and clean termination.
- Kills ONLY the process created by this application (never pkill generic names).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional
from localtext.config import get_private_runtime_dir
from localtext.inference.runtime_auth import RuntimeAuthManager
from localtext.utils.logging import setup_privacy_logger

logger = setup_privacy_logger("llama_process", log_to_file=True)


class ProcessManagementError(RuntimeError):
    """Raised when the inference child process fails to launch or becomes unresponsive."""
    pass


def find_free_loopback_port() -> int:
    """Find a free port on numeric loopback 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port


class ManagedLlamaServer:
    """Supervises the lifecycle of a local llama-server child process."""

    def __init__(
        self,
        model_path: Path,
        executable_path: str = "llama-server",
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        context_tokens: int = 4096,
        threads: int = 16,
        auth_manager: Optional[RuntimeAuthManager] = None,
    ):
        # Guarantee numeric loopback binding only (NFR-03)
        if host not in {"127.0.0.1", "::1"}:
            raise ValueError(f"Inference server must bind strictly to numeric loopback. Got: '{host}'")

        self.model_path = model_path
        self.executable_path = executable_path
        self.host = host
        self.port = port or find_free_loopback_port()
        self.context_tokens = context_tokens
        self.threads = threads
        self.auth_manager = auth_manager or RuntimeAuthManager()
        self.process: Optional[subprocess.Popen] = None
        self._is_ready: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def build_command_args(self) -> List[str]:
        """Build argument array with no shell interpolation (Section 6)."""
        secret_key = self.auth_manager.generate_secret()
        key_file = self.auth_manager.key_file_path

        args = [
            self.executable_path,
            "-m", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "-c", str(self.context_tokens),
            "-t", str(self.threads),
            "--api-key-file", str(key_file),
            "--log-disable",  # Suppress default request text logging (NFR-09)
            "--no-mmap",      # Ensure clean OS memory release
        ]
        return args

    def start(self, timeout_seconds: float = 30.0) -> None:
        """Launch the server process and wait for readiness."""
        if self.is_running:
            return

        if not self.model_path.exists():
            raise ProcessManagementError(
                f"Model weights file not found at '{self.model_path}'. "
                f"Run model installation script first."
            )

        cmd = self.build_command_args()
        logger.info(f"Starting inference server on {self.host}:{self.port} (PID tracking enabled)")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # Isolate process group
            )
        except FileNotFoundError:
            raise ProcessManagementError(
                f"Inference binary '{self.executable_path}' not found on system. "
                f"Ensure llama.cpp is built or installed."
            )
        except Exception as e:
            raise ProcessManagementError(f"Failed to spawn inference server: {e}")

        # Wait for server readiness on loopback
        start_t = time.perf_counter()
        while time.perf_counter() - start_t < timeout_seconds:
            if not self.is_running:
                stderr = ""
                if self.process and self.process.stderr:
                    stderr = self.process.stderr.read().decode("utf-8", errors="ignore")
                raise ProcessManagementError(
                    f"Inference server exited prematurely with code {self.process.returncode}. Stderr: {stderr[:300]}"
                )
            if self._check_health():
                self._is_ready = True
                logger.info("Inference server is healthy and accepting requests.")
                return
            time.sleep(0.2)

        # Timed out waiting for readiness
        self.terminate(force_timeout=2.0)
        raise ProcessManagementError(
            f"Timed out ({timeout_seconds}s) waiting for inference server on {self.base_url}."
        )

    def _check_health(self) -> bool:
        """Check if listener is accepting connections."""
        try:
            with socket.create_connection((self.host, self.port), timeout=0.5):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def terminate(self, force_timeout: float = 5.0) -> None:
        """Gracefully terminate owned process, escalating to SIGKILL if unresponsive (AT-10, NFR-07)."""
        if not self.process:
            self.auth_manager.cleanup()
            return

        pid = self.process.pid
        logger.info(f"Terminating inference server (PID {pid})")

        try:
            # 1. Send SIGTERM to entire process group
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        # 2. Wait up to force_timeout seconds for clean exit (AT-10: release within 5s)
        start_t = time.perf_counter()
        while time.perf_counter() - start_t < force_timeout:
            if self.process.poll() is not None:
                break
            time.sleep(0.1)

        # 3. If still alive after timeout, send SIGKILL
        if self.process.poll() is None:
            logger.warning(f"Process PID {pid} unresponsive after {force_timeout}s; sending SIGKILL")
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            self.process.kill()

        self.process = None
        self._is_ready = False
        self.auth_manager.cleanup()
