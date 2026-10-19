"""Unit tests for detection pipeline and classifier boundary behavior.

Verifies DET-01, DET-02, DET-03, DET-04, AT-03, AT-04, AT-12, and AT-20.
"""

import unittest
from pathlib import Path
from localtext.contracts import DetectorLabel, ValidationStatus
from localtext.detection.calibrator import DetectorCalibrator
from localtext.detection.model_loader import AuditedDetectorLoader, ModelLoadError
from localtext.detection.pipeline import DetectionPipeline
from localtext.detection.preprocessor import DetectionPreprocessor


class TestDetectionPipeline(unittest.TestCase):
    def setUp(self):
        self.preprocessor = DetectionPreprocessor(supported_languages=("en",), min_prose_words=150)
        self.calibrator = DetectorCalibrator(tau_low=30.0, tau_high=70.0, is_calibrated=True)
        self.pipeline = DetectionPipeline(
            preprocessor=self.preprocessor,
            calibrator=self.calibrator,
            model_id="desklib-v1.01-en",
            validation_status=ValidationStatus.EXPERIMENTAL,
        )

    def test_at03_insufficient_text_handling(self):
        """AT-03: Empty, whitespace, or <150 words produces Insufficient text without score."""
        # 1. Empty string
        res_empty = self.pipeline.run_detection("job-1", 1, "", language="en")
        self.assertEqual(res_empty.label, DetectorLabel.INSUFFICIENT_TEXT)
        self.assertIsNone(res_empty.score)

        # 2. Whitespace only
        res_space = self.pipeline.run_detection("job-2", 1, "   \n\n\t  ", language="en")
        self.assertEqual(res_space.label, DetectorLabel.INSUFFICIENT_TEXT)
        self.assertIsNone(res_space.score)

        # 3. 30 words
        short_text = "This is a brief piece of text containing only a small number of words that does not meet the one hundred and fifty word threshold for detection analysis."
        res_short = self.pipeline.run_detection("job-3", 1, short_text, language="en")
        self.assertEqual(res_short.label, DetectorLabel.INSUFFICIENT_TEXT)
        self.assertIsNone(res_short.score)
        self.assertIn("150", res_short.score_semantics)

    def test_at04_unsupported_language_routing(self):
        """AT-04: German text when only English detector installed returns Unsupported language."""
        german_prose = "Dies ist ein deutscher Text " * 30  # 180 words
        res_de = self.pipeline.run_detection("job-de", 1, german_prose, language="de")
        self.assertEqual(res_de.label, DetectorLabel.UNSUPPORTED_CONTENT)
        self.assertIsNone(res_de.score)
        self.assertIn("not supported", res_de.score_semantics)

    def test_at20_classifier_boundary_fixtures(self):
        """AT-20: Synthetic boundary fixtures verify label direction and thresholds."""
        # 160 words of text
        prose = "The method uses modern deep learning architectures to analyze long documents. " * 16

        # Case 1: Strongly AI logit (e.g. +3.0) -> Score >= 70 -> Strong AI signal
        res_ai = self.pipeline.run_detection(
            "job-ai", 1, prose, language="en", mock_window_scorer=lambda _: 3.0
        )
        self.assertEqual(res_ai.label, DetectorLabel.STRONG_AI)
        self.assertIsNotNone(res_ai.score)
        self.assertGreaterEqual(res_ai.score, 70.0)

        # Case 2: Strongly human logit (e.g. -3.0) -> Score <= 30 -> Low AI signal
        res_human = self.pipeline.run_detection(
            "job-human", 1, prose, language="en", mock_window_scorer=lambda _: -3.0
        )
        self.assertEqual(res_human.label, DetectorLabel.LOW_AI)
        self.assertIsNotNone(res_human.score)
        self.assertLessEqual(res_human.score, 30.0)

        # Case 3: Boundary / Uncertain logit (e.g. 0.0 -> score 50.0) -> Uncertain
        res_unc = self.pipeline.run_detection(
            "job-unc", 1, prose, language="en", mock_window_scorer=lambda _: 0.0
        )
        self.assertEqual(res_unc.label, DetectorLabel.UNCERTAIN)
        self.assertIsNotNone(res_unc.score)
        self.assertEqual(res_unc.score, 50.0)

    def test_at12_audited_loader_key_mismatch(self):
        """AT-12: Audited loader detects missing classifier keys and prevents random initialization."""
        loader = AuditedDetectorLoader()

        # Checkpoint with missing classifier head
        corrupt_keys = {"model.encoder.layer.0.weight", "model.embeddings.word_embeddings.weight"}
        is_valid, errors = loader.audit_state_dict_keys(corrupt_keys)
        self.assertFalse(is_valid)
        self.assertTrue(any("classifier.weight" in e for e in errors))

        # Checkpoint with valid keys
        valid_keys = {
            "model.encoder.layer.0.weight",
            "classifier.weight",
            "classifier.bias",
        }
        is_valid_ok, errors_ok = loader.audit_state_dict_keys(valid_keys)
        self.assertTrue(is_valid_ok)
        self.assertEqual(errors_ok, [])


if __name__ == "__main__":
    unittest.main()

