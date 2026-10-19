"""Unit tests for memory admission check.

Verifies NFR-06 and AT-13:
- Memory headroom too small for 27B: refuse profile gracefully and offer 9B alternative.
- Keep at least 6.0 GiB available for the OS.
"""

import unittest
from localtext.inference.memory_guard import MemoryGuard, MemoryAdmissionError


class TestMemoryGuard(unittest.TestCase):
    def setUp(self):
        self.guard = MemoryGuard(min_headroom_bytes=6 * 1024 * 1024 * 1024)

    def test_9b_profile_admitted_with_sufficient_ram(self):
        # 18 GiB available RAM: 18 - 10.5 = 7.5 GiB headroom >= 6 GiB -> PASS
        decision = self.guard.check_admission(
            "qwen-9b-q6k", mock_available_bytes=18 * 1024 * 1024 * 1024
        )
        self.assertTrue(decision.allowed)
        self.assertIn("admission passed", decision.message)

    def test_27b_profile_refused_on_typical_32gb_laptop(self):
        # Even with 20 GiB available RAM: 20 - 23.6 = -3.6 GiB headroom < 6 GiB -> FAIL
        decision = self.guard.check_admission(
            "qwen-27b-q4km", mock_available_bytes=20 * 1024 * 1024 * 1024
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.recommended_alternative, "qwen-9b-q6k")
        self.assertIn("falls below mandatory OS reserve", decision.message)
        self.assertIn("qwen-9b-q6k", decision.message)

    def test_enforce_admission_raises_exception(self):
        with self.assertRaises(MemoryAdmissionError) as ctx:
            self.guard.enforce_admission(
                "qwen-27b-q4km", mock_available_bytes=15 * 1024 * 1024 * 1024
            )
        self.assertFalse(ctx.exception.decision.allowed)
        self.assertEqual(ctx.exception.decision.recommended_alternative, "qwen-9b-q6k")

    def test_real_system_check_does_not_crash(self):
        # Test against real psutil system query on the current host
        decision = self.guard.check_admission("desklib-v1.01-en")
        self.assertIsInstance(decision.allowed, bool)
        self.assertGreater(decision.available_bytes, 0)


if __name__ == "__main__":
    unittest.main()
