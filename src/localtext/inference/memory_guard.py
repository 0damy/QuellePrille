"""Memory Admission Guard for local inference runtimes.

Adheres strictly to NFR-06 and Acceptance Test AT-13.
Guarantees at least 6.0 GiB remains available for the OS and applications.
Refuses models that exceed safe headroom rather than crashing or causing heavy swap.
"""

from __future__ import annotations

import psutil
from dataclasses import dataclass
from typing import Optional
from localtext.config import MIN_OS_HEADROOM_BYTES


# Conservative peak footprint estimates in bytes (including weights, context, KV caches, runtime overhead)
MODEL_PEAK_FOOTPRINT_BYTES = {
    # 9B GGUF Q6_K: ~8 GB weights + ~2.5 GB context/runtime peak = ~10.5 GB
    "qwen-9b-q6k": 10_500_000_000,
    # 27B GGUF Q4_K_M: ~19.1 GB weights + ~4.5 GB context/runtime peak = ~23.6 GB
    "qwen-27b-q4km": 23_600_000_000,
    # DeBERTa-v3-large detector: ~1.7 GB weights + ~0.8 GB activations = ~2.5 GB
    "desklib-v1.01-en": 2_500_000_000,
    # XLM-RoBERTa-large detector: ~2.2 GB weights + ~0.8 GB activations = ~3.0 GB
    "oculus-v2.0-multi": 3_000_000_000,
}

ALTERNATIVE_PROFILES = {
    "qwen-27b-q4km": "qwen-9b-q6k",
}


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    model_profile_id: str
    required_bytes: int
    available_bytes: int
    headroom_bytes: int
    message: str
    recommended_alternative: Optional[str] = None


class MemoryAdmissionError(RuntimeError):
    """Raised when a model profile fails the admission check due to inadequate memory."""
    def __init__(self, decision: AdmissionDecision):
        super().__init__(decision.message)
        self.decision = decision


class MemoryGuard:
    """Performs pre-load memory admission checks based on real measured OS state."""

    def __init__(self, min_headroom_bytes: int = MIN_OS_HEADROOM_BYTES):
        self.min_headroom_bytes = min_headroom_bytes

    def get_available_memory_bytes(self) -> int:
        """Query authoritative current available memory from the OS."""
        vm = psutil.virtual_memory()
        return vm.available

    def check_admission(
        self,
        model_profile_id: str,
        custom_footprint_bytes: Optional[int] = None,
        mock_available_bytes: Optional[int] = None,
    ) -> AdmissionDecision:
        """Evaluate if model loading is safe without violating the minimum OS headroom."""
        available = (
            mock_available_bytes
            if mock_available_bytes is not None
            else self.get_available_memory_bytes()
        )

        required = (
            custom_footprint_bytes
            if custom_footprint_bytes is not None
            else MODEL_PEAK_FOOTPRINT_BYTES.get(model_profile_id, 4_000_000_000)
        )

        safe_max_allocation = max(0, available - self.min_headroom_bytes)
        headroom_after_load = available - required

        if headroom_after_load < self.min_headroom_bytes:
            alternative = ALTERNATIVE_PROFILES.get(model_profile_id)
            alt_msg = (
                f" Recommended alternative profile: '{alternative}'."
                if alternative
                else ""
            )
            msg = (
                f"Memory admission check failed for profile '{model_profile_id}'. "
                f"Estimated peak memory: {required / (1024**3):.2f} GiB. "
                f"System available RAM: {available / (1024**3):.2f} GiB. "
                f"Remaining headroom ({headroom_after_load / (1024**3):.2f} GiB) falls below "
                f"mandatory OS reserve of {self.min_headroom_bytes / (1024**3):.2f} GiB.{alt_msg}"
            )
            return AdmissionDecision(
                allowed=False,
                model_profile_id=model_profile_id,
                required_bytes=required,
                available_bytes=available,
                headroom_bytes=headroom_after_load,
                message=msg,
                recommended_alternative=alternative,
            )

        return AdmissionDecision(
            allowed=True,
            model_profile_id=model_profile_id,
            required_bytes=required,
            available_bytes=available,
            headroom_bytes=headroom_after_load,
            message=(
                f"Memory admission passed for '{model_profile_id}'. "
                f"Projected available RAM after loading: {headroom_after_load / (1024**3):.2f} GiB."
            ),
        )

    def enforce_admission(
        self,
        model_profile_id: str,
        custom_footprint_bytes: Optional[int] = None,
        mock_available_bytes: Optional[int] = None,
    ) -> AdmissionDecision:
        """Check admission and raise MemoryAdmissionError if not allowed."""
        decision = self.check_admission(
            model_profile_id, custom_footprint_bytes, mock_available_bytes
        )
        if not decision.allowed:
            raise MemoryAdmissionError(decision)
        return decision
