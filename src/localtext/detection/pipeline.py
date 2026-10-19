"""High-level detection pipeline coordinating preprocessing, windowing, aggregation, and calibration.

Production calls load real local weights; synthetic scores are an explicit test seam.
"""

from __future__ import annotations

import time
import math
import re
from pathlib import Path
from localtext.config import get_models_dir
from localtext.detection.model_loader import LocalDesklibDetector
from localtext.inference.ollama_client import check_cancelled
from localtext.rephrase.chunker import DocumentChunker
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
        calibration_id: str = "",
        validation_status: ValidationStatus = ValidationStatus.UNVALIDATED,
        model_dir: Optional[Path] = None,
        detector=None,
    ):
        self.preprocessor = preprocessor or DetectionPreprocessor(supported_languages=("en",))
        self.aggregator = aggregator or DocumentAggregator(max_window_tokens=512, overlap_tokens=64)
        self.calibrator = calibrator or DetectorCalibrator(is_calibrated=False)
        self.model_dir = model_dir
        self.detector = detector
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
        cancel_event=None,
    ) -> DetectionResult:
        """Execute full detection pipeline on given text snapshot."""
        start_time = time.perf_counter()
        DocumentChunker().validate_document_limits(text)
        check_cancelled(cancel_event)

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

        # Tokenize each eligible span separately so excluded text is never scored.
        # The synthetic scorer is retained solely for deterministic boundary tests.
        if mock_window_scorer is None and self.detector is None:
            self.detector = LocalDesklibDetector(self.model_dir or get_models_dir() / "desklib")
        check_cancelled(cancel_event)
        window_logits = []
        passage_scores = []
        weights = []
        for span in prep.eligible_spans:
            prose = span.slice_from(text)
            if mock_window_scorer is not None:
                matches = list(re.finditer(r"\S+", prose))
                ids = [m.group() for m in matches]
                offsets = [m.span() for m in matches]
                aggregator = self.aggregator
            else:
                ids, offsets = self.detector.tokenize(prose)
                aggregator = DocumentAggregator(self.detector.window_tokens, 64)
            absolute_offsets = [(span.start + a, span.start + b) for a, b in offsets]
            windows = aggregator.create_windows(len(ids), absolute_offsets)
            weights.extend(aggregator.compute_coverage_weights(len(ids), windows))
            for win in windows:
                check_cancelled(cancel_event)
                subset = ids[win.token_indices[0]:win.token_indices[-1] + 1]
                logit = (mock_window_scorer(" ".join(subset)) if mock_window_scorer is not None
                         else self.detector.score_tokens(subset))
                if not math.isfinite(logit):
                    raise ValueError("Detector produced a non-finite score.")
                window_logits.append(logit)
                passage_scores.append(PassageScore(
                    window_id=len(passage_scores), span=win.char_span, raw_logit=logit,
                    calibrated_score=(self.calibrator.logit_to_score(logit)
                                      if self.calibrator.is_calibrated else None),
                    token_count=len(subset),
                ))
        check_cancelled(cancel_event)
        if not window_logits:
            raise ValueError("No detector tokens found in eligible prose.")

        # 4. Aggregate window logits (Section 9)
        doc_logit = self.aggregator.aggregate_logits(window_logits, weights)

        # 5. Calibrate & evaluate decision (DET-02, DET-04, AT-20)
        decision = self.calibrator.evaluate_decision(doc_logit)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        coverage_ratio = (
            sum(sp.length for sp in prep.eligible_spans) / max(1, len(text))
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
            raw_model_score=DetectorCalibrator().logit_to_score(doc_logit),
        )

