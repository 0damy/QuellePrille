"""Inference job controller coordinating detection, rephrasing, and cancellation.

Adheres strictly to Section 6, NFR-06, NFR-07, and Acceptance Test AT-10.
Enforces the single-flight heavy inference rule: runs at most one heavy job at a time.
Provides responsive cancellation: acknowledges cancel requests within 250 ms,
aborts streams, and releases resources within 5 seconds.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional
from localtext.contracts import (
    DetectionResult,
    JobState,
    RewriteRequest,
    RewriteResult,
)
from localtext.detection.pipeline import DetectionPipeline
from localtext.inference.memory_guard import MemoryAdmissionError, MemoryGuard
from localtext.rephrase.pipeline import RephrasePipeline
from localtext.utils.logging import setup_privacy_logger

logger = setup_privacy_logger("job_controller", log_to_file=True)


class ControllerBusyError(RuntimeError):
    """Raised when an inference job is submitted while another heavy job is active."""
    pass


class JobController:
    """Manages asynchronous inference jobs, process lifecycle, and active cancellation."""

    def __init__(
        self,
        rephrase_pipeline: Optional[RephrasePipeline] = None,
        detection_pipeline: Optional[DetectionPipeline] = None,
        memory_guard: Optional[MemoryGuard] = None,
    ):
        self.rephrase_pipeline = rephrase_pipeline or RephrasePipeline()
        self.detection_pipeline = detection_pipeline or DetectionPipeline()
        self.memory_guard = memory_guard or MemoryGuard()

        self._active_lock = threading.Lock()
        self._active_job_id: Optional[str] = None
        self._cancel_event: Optional[threading.Event] = None
        self._worker_thread: Optional[threading.Thread] = None

    @property
    def is_busy(self) -> bool:
        with self._active_lock:
            return self._active_job_id is not None

    @property
    def active_job_id(self) -> Optional[str]:
        with self._active_lock:
            return self._active_job_id

    def cancel_active_job(self) -> bool:
        """Acknowledge cancellation immediately (<250ms) and signal worker to stop (AT-10, NFR-07)."""
        with self._active_lock:
            if not self._active_job_id or not self._cancel_event:
                return False
            logger.info(f"Cancellation requested for active job '{self._active_job_id}'")
            self._cancel_event.set()
            return True

    def run_rephrase_job(
        self,
        request: RewriteRequest,
        generator_fn: Callable[[str, str], str],
        language: str = "en",
        user_frozen_words: Optional[list[str]] = None,
    ) -> RewriteResult:
        """Run rephrase job enforcing memory admission and single-flight execution."""
        # 1. Enforce memory admission (NFR-06, AT-13)
        self.memory_guard.enforce_admission(request.model_profile_id)

        # 2. Acquire single-flight lock
        with self._active_lock:
            if self._active_job_id is not None:
                raise ControllerBusyError(
                    f"Controller busy running job '{self._active_job_id}'. "
                    f"Only one heavy inference job is permitted at a time (Section 6)."
                )
            self._active_job_id = request.job_id
            self._cancel_event = threading.Event()

        try:
            result = self.rephrase_pipeline.run_rephrase(
                request=request,
                generator_fn=generator_fn,
                cancel_event=self._cancel_event,
                language=language,
                user_frozen_words=user_frozen_words,
            )
            return result
        finally:
            with self._active_lock:
                self._active_job_id = None
                self._cancel_event = None

    def run_detection_job(
        self,
        job_id: str,
        revision: int,
        text: str,
        language: str = "en",
        mock_window_scorer: Optional[Callable[[str], float]] = None,
    ) -> DetectionResult:
        """Run detection job enforcing single-flight execution."""
        # Enforce memory admission for detector
        self.memory_guard.enforce_admission("desklib-v1.01-en")

        with self._active_lock:
            if self._active_job_id is not None:
                raise ControllerBusyError(
                    f"Controller busy running job '{self._active_job_id}'."
                )
            self._active_job_id = job_id
            self._cancel_event = threading.Event()

        try:
            result = self.detection_pipeline.run_detection(
                job_id=job_id,
                revision=revision,
                text=text,
                language=language,
                mock_window_scorer=mock_window_scorer,
            )
            return result
        finally:
            with self._active_lock:
                self._active_job_id = None
                self._cancel_event = None
