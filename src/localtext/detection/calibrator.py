"""Score calibration and decision boundary classifier for AI text detection.

Adheres strictly to DET-02, DET-04, and Acceptance Test AT-20.
Maps raw aggregated logits to a calibrated 0–100 model score using frozen profile parameters.
Applies locked decision thresholds tau_low and tau_high to produce truthful labels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional
from localtext.contracts import DetectorLabel


@dataclass(frozen=True)
class CalibratedDecision:
    label: DetectorLabel
    calibrated_score: Optional[float]  # 0.0 to 100.0, or None if uncalibrated
    raw_logit: float
    semantics: str
    tau_low: float
    tau_high: float


class DetectorCalibrator:
    """Calibrates raw logits and evaluates decision boundaries."""

    def __init__(
        self,
        tau_low: float = 30.0,
        tau_high: float = 70.0,
        scale_a: float = 1.0,
        bias_b: float = 0.0,
        is_calibrated: bool = False,
    ):
        if tau_low >= tau_high:
            raise ValueError(f"tau_low ({tau_low}) must be strictly less than tau_high ({tau_high})")
        self.tau_low = tau_low
        self.tau_high = tau_high
        self.scale_a = scale_a
        self.bias_b = bias_b
        self.is_calibrated = is_calibrated

    def logit_to_score(self, raw_logit: float) -> float:
        """Apply logistic calibration and scale to 0.0 - 100.0."""
        # Platt scaling: p = 1 / (1 + exp(-(a * z + b)))
        x = self.scale_a * raw_logit + self.bias_b
        # Prevent math overflow
        if x > 40.0:
            prob = 1.0
        elif x < -40.0:
            prob = 0.0
        else:
            prob = 1.0 / (1.0 + math.exp(-x))
        return round(prob * 100.0, 1)

    def evaluate_decision(self, raw_logit: float) -> CalibratedDecision:
        """Classify raw logit into Strong AI, Low AI, or Uncertain (DET-02, AT-20)."""
        if not self.is_calibrated:
            # DET-04: Hide normal scores when no valid calibration profile exists
            return CalibratedDecision(
                label=DetectorLabel.UNCERTAIN,
                calibrated_score=None,
                raw_logit=raw_logit,
                semantics="Uncalibrated profile: raw logit available for inspection only.",
                tau_low=self.tau_low,
                tau_high=self.tau_high,
            )

        score = self.logit_to_score(raw_logit)

        if score >= self.tau_high:
            label = DetectorLabel.STRONG_AI
            semantics = (
                f"Model score {score:.1f}/100 exceeds high threshold ({self.tau_high:.1f}). "
                "Strong statistical signal of AI generation within validated distribution."
            )
        elif score <= self.tau_low:
            label = DetectorLabel.LOW_AI
            semantics = (
                f"Model score {score:.1f}/100 falls below low threshold ({self.tau_low:.1f}). "
                "Low AI signal detected. Note: Low signal does not prove human authorship."
            )
        else:
            label = DetectorLabel.UNCERTAIN
            semantics = (
                f"Model score {score:.1f}/100 falls in uncertainty region between "
                f"{self.tau_low:.1f} and {self.tau_high:.1f}. Inconclusive evidence."
            )

        return CalibratedDecision(
            label=label,
            calibrated_score=score,
            raw_logit=raw_logit,
            semantics=semantics,
            tau_low=self.tau_low,
            tau_high=self.tau_high,
        )

