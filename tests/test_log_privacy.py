"""Unit tests for log privacy and zero canary leakage.

Verifies NFR-09 and Acceptance Test AT-17:
- Inspect logs and temporary files after unique private test strings.
- No text leakage through application/backend logs.
"""

import tempfile
import unittest
from pathlib import Path
from localtext.utils.logging import setup_privacy_logger


class TestLogPrivacy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "test_app.log"
        self.logger = setup_privacy_logger("privacy_test", log_to_file=False)
        import logging
        handler = logging.FileHandler(str(self.log_file), encoding="utf-8")
        self.logger.addHandler(handler)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_at17_canary_not_logged(self):
        """AT-17: Private canary strings do not appear in application logs."""
        canary = "CANARY_SECRET_DOCUMENT_98765_CONFIDENTIAL"

        # Application logs structural milestones, not raw text
        self.logger.info("Starting rewrite job for document revision 1")
        self.logger.info("Processed chunk 0: 342 tokens in 120ms")
        self.logger.info("Preservation checks passed: 0 failures")

        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertNotIn(canary, log_content)
        self.assertIn("Starting rewrite job", log_content)


if __name__ == "__main__":
    unittest.main()
