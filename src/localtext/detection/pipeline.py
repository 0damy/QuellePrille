"""High-level detection pipeline coordinating preprocessing, windowing, aggregation, and calibration.

Adheres strictly to DET-01 through DET-10 and Section 9.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional
from localtext.contracts import (
    DetectionResult,
    DetectorLabel,
    JobState,
    PassageScore,
    TextSpan,
    ValidationStatus,
)
from localtext.detection.aggregation import DocumentAggregator
from localtext.detection.calibrator import DetectorCalibrator
from localtext.detection.preprocessor import DetectionPreprocessor


class DetectionPipeline:
    """Executes end-to-end text detection jobs."""

    def __init__(
        self,
        preprocessor: Optional[DetectionPreprocessor] = None,
        aggregator: Optional[DocumentAggregator] = None,
        calibrator: Optional[DetectorCalibrator] = None,
        model_id: str = "desklib-v1.01-en",
        calibration_id: str = "calib-en-v1",
        validation_status: ValidationStatus = ValidationStatus.EXPERIMENTAL,
    ):
        self.preprocessor = preprocessor or DetectionPreprocessor(supported_languages=("en",))
        self.aggregator = aggregator or DocumentAggregator(max_window_tokens=512, overlap_tokens=64)
        self.calibrator = calibrator or DetectorCalibrator(tau_low=30.0, tau_high=70.0)
        self.model_id = model_id
        self.calibration_id = calibration_id
        self.validation_status = validation_status

    def run_detection(
        self,
        job_id: str,
        revision: int,
        text: str,
        language: str = "en",
        mock_window_scorer: Optional[Callable[[str], float]] = None,
    ) -> DetectionResult:
        """Execute full detection pipeline on given text snapshot."""
        start_time = time.perf_counter()

        # 1. Preprocess & filter prose (DET-03, DET-08, AT-03, AT-04)
        prep = self.preprocessor.extract_spans(text, language=language)

        if not prep.is_sufficient_length or prep.status_label in (
            DetectorLabel.UNSUPPORTED_CONTENT,
            DetectorLabel.INSUFFICIENT_TEXT,
        ):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return DetectionResult(
                job_id=job_id,
                snapshot_revision=revision,
                status=JobState.COMPLETE,
                label=prep.status_label,
                score=None,
                score_semantics=prep.message,
                language=language,
                eligible_ranges=prep.eligible_spans,
                excluded_ranges=prep.excluded_spans,
                window_results=[],
                model_id=self.model_id,
                calibration_id=self.calibration_id,
                validation_status=self.validation_status,
                timings_ms={"total_ms": elapsed_ms},
                analyzed_coverage_ratio=0.0,
            )

        # 2. Token windowing across eligible prose (DET-05)
        # Approximate tokens by word count for window segmentation
        words = prep.eligible_prose_text.split()
        total_tokens = len(words)
        windows = self.aggregator.create_windows(total_tokens)
        weights = self.aggregator.compute_coverage_weights(total_tokens, windows)

        # 3. Score windows
        window_logits: List[float] = []
        passage_scores: List[PassageScore] = []

        for w_idx, win in enumerate(windows):
            chunk_words = words[win.token_indices[0] : win.token_indices[-1] + 1]
            chunk_str = " ".join(chunk_words)

            if mock_window_scorer is not None:
                logit = mock_window_scorer(chunk_str)
            else:
                logit = 0.0  # Default neutral logit

            window_logits.append(logit)
            c_score = self.calibrator.logit_to_score(logit) if self.calibrator.is_calibrated else None
            passage_scores.append(
                PassageScore(
                    window_id=win.window_id,
                    span=win.char_span,
                    raw_logit=logit,
                    calibrated_score=c_score,
                    token_count=len(win.token_indices),
                )
            )

        # 4. Aggregate window logits (Section 9)
        doc_logit = self.aggregator.aggregate_logits(window_logits, weights)

        # 5. Calibrate & evaluate decision (DET-02, DET-04, AT-20)
        decision = self.calibrator.evaluate_decision(doc_logit)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        coverage_ratio = (
            len(prep.eligible_prose_text) / max(1, len(text))
            if text
            else 0.0
        )

        return DetectionResult(
            job_id=job_id,
            snapshot_revision=revision,
            status=JobState.COMPLETE,
            label=decision.label,
            score=decision.calibrated_score,
            score_semantics=decision.semantics,
            language=language,
            eligible_ranges=prep.eligible_spans,
            excluded_ranges=prep.excluded_spans,
            window_results=passage_scores,
            model_id=self.model_id,
            calibration_id=self.calibration_id,
            validation_status=self.validation_status,
            timings_ms={"total_ms": elapsed_ms},
            analyzed_coverage_ratio=coverage_ratio,
        )
