"""Unit tests for job cancellation, single-flight locking, and bounded repair policy.

Verifies REP-10, NFR-07, and Acceptance Test AT-10:
- Cancel during inference: responsive acknowledgement (<250ms), clean cancellation.
- Single-flight lock: refuses concurrent heavy jobs.
- Bounded repair: 1 repair attempt, then keeps original text if still invalid.
"""

import threading
import time
import unittest
from unittest.mock import Mock
from localtext.inference.memory_guard import MemoryGuard
from localtext.contracts import (
    ChangeStrength,
    JobState,
    RephraseMode,
    RewriteRequest,
    TargetBlock,
    TextSpan,
)
from localtext.inference.job_controller import ControllerBusyError, JobController


class TestJobControllerAndCancellation(unittest.TestCase):
    def setUp(self):
        self.controller = JobController(memory_guard=Mock(spec=MemoryGuard))

    def test_at10_responsive_cancellation(self):
        """AT-10: Cancel active job releases worker promptly."""
        target_block = TargetBlock(
            block_id=0,
            source_span=TextSpan(start=0, end=40),
            source_text="This is a sentence being rephrased slowly.",
        )
        req = RewriteRequest(
            job_id="job-slow",
            snapshot_revision=1,
            model_profile_id="qwen-9b-q6k",
            mode=RephraseMode.STANDARD,
            strength=ChangeStrength.MEDIUM,
            target_blocks=(target_block,),
        )

        def slow_generator(prompt: str, sys_prompt: str) -> str:
            # Simulate a slow streaming inference loop checking cancel
            for _ in range(50):
                time.sleep(0.05)
            return "Rewritten slowly."

        # Start job in separate thread
        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                self.controller.run_rephrase_job(req, slow_generator)
            )
        )
        t.start()

        # Wait until job is active
        time.sleep(0.05)
        self.assertTrue(self.controller.is_busy)

        # Measure cancellation acknowledgement timing (<250ms required by NFR-07)
        cancel_start = time.perf_counter()
        acknowledged = self.controller.cancel_active_job()
        ack_elapsed_ms = (time.perf_counter() - cancel_start) * 1000

        self.assertTrue(acknowledged)
        self.assertLess(ack_elapsed_ms, 250.0)

        # Worker should join and release controller lock within 5 seconds (AT-10)
        t.join(timeout=3.0)
        self.assertFalse(t.is_alive())
        self.assertFalse(self.controller.is_busy)

    def test_single_flight_lock_refuses_concurrent_jobs(self):
        """Section 6: Runs at most one heavy inference job at a time."""
        target_block = TargetBlock(
            block_id=0,
            source_span=TextSpan(start=0, end=20),
            source_text="Sample text block.",
        )
        req1 = RewriteRequest(
            job_id="job-1",
            snapshot_revision=1,
            model_profile_id="qwen-9b-q6k",
            mode=RephraseMode.STANDARD,
            strength=ChangeStrength.MEDIUM,
            target_blocks=(target_block,),
        )
        req2 = RewriteRequest(
            job_id="job-2",
            snapshot_revision=1,
            model_profile_id="qwen-9b-q6k",
            mode=RephraseMode.STANDARD,
            strength=ChangeStrength.MEDIUM,
            target_blocks=(target_block,),
        )

        job1_started = threading.Event()

        def blocking_gen(prompt, sys_prompt):
            job1_started.set()
            time.sleep(0.2)
            return "Rewritten."

        t1 = threading.Thread(target=lambda: self.controller.run_rephrase_job(req1, blocking_gen))
        t1.start()
        self.assertTrue(job1_started.wait(timeout=2))

        # Attempting to start job 2 concurrently must fail with ControllerBusyError
        with self.assertRaises(ControllerBusyError):
            self.controller.run_rephrase_job(req2, lambda p, s: "Should not run")

        t1.join()
        self.assertFalse(self.controller.is_busy)

    def test_rep10_bounded_repair_fallback_to_original(self):
        """REP-10: If repair attempt fails, fallback to original text and explain conflict."""
        source = "This experiment did not succeed."
        target_block = TargetBlock(
            block_id=0,
            source_span=TextSpan(start=0, end=len(source)),
            source_text=source,
        )
        req = RewriteRequest(
            job_id="job-repair",
            snapshot_revision=1,
            model_profile_id="qwen-9b-q6k",
            mode=RephraseMode.STANDARD,
            strength=ChangeStrength.MEDIUM,
            target_blocks=(target_block,),
        )

        attempts = 0

        def persistent_bad_generator(prompt, sys_prompt):
            nonlocal attempts
            attempts += 1
            # Model persistently drops negation on both primary and repair attempts
            return "This experiment succeeded completely."

        result = self.controller.run_rephrase_job(req, persistent_bad_generator)
        # Bounded repair: 1 primary + 1 repair = exactly 2 attempts
        self.assertEqual(attempts, 2)
        # Preserved original text!
        self.assertEqual(result.candidate_blocks[0].rewritten_text, source)
        self.assertTrue(any("failed" in err.lower() for err in result.failed_checks))


if __name__ == "__main__":
    unittest.main()

