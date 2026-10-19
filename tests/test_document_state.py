"""Unit tests for document state management, undo/redo, and stale result invalidation.

Verifies APP-05, REP-09, and AT-11:
- AT-11: Edit source while a job runs: previous result remains attached to its old revision and cannot overwrite the new text.
- REP-09: Accept/reject individual rewritten blocks and undo acceptance.
"""

import unittest
from localtext.contracts import CandidateBlock, JobState, RewriteResult
from localtext.storage.document_state import DocumentStateManager


class TestDocumentState(unittest.TestCase):
    def setUp(self):
        self.doc = DocumentStateManager(initial_text="Initial text revision 1.")

    def test_text_editing_bumps_revision_and_marks_stale(self):
        self.assertEqual(self.doc.revision, 1)
        self.doc.set_text("Updated text revision 2.")
        self.assertEqual(self.doc.revision, 2)
        self.assertTrue(self.doc.is_result_stale)

    def test_undo_and_redo(self):
        self.doc.set_text("Text revision 2.")
        self.assertEqual(self.doc.text, "Text revision 2.")
        
        self.assertTrue(self.doc.undo())
        self.assertEqual(self.doc.text, "Initial text revision 1.")

        self.assertTrue(self.doc.redo())
        self.assertEqual(self.doc.text, "Text revision 2.")

    def test_at11_stale_result_cannot_overwrite_newer_text(self):
        """AT-11: Result from revision 1 cannot overwrite revision 2 text."""
        # User requested rewrite at revision 1
        res_rev1 = RewriteResult(
            job_id="job-1",
            snapshot_revision=1,
            status=JobState.COMPLETE,
            candidate_blocks=[
                CandidateBlock(block_id=0, candidate_id=0, rewritten_text="Rewritten rev 1")
            ],
        )

        # While job was running, user edited text -> revision 2
        self.doc.set_text("User made further edits here.")
        self.assertEqual(self.doc.revision, 2)

        # Finished job for revision 1 attempts to attach
        attached = self.doc.attach_rewrite_result(res_rev1)
        self.assertFalse(attached)  # Refused!
        self.assertTrue(self.doc.is_result_stale)
        self.assertEqual(self.doc.text, "User made further edits here.")

    def test_rep09_block_accept_reject(self):
        """REP-09: Accept and reject individual rewritten blocks."""
        res = RewriteResult(
            job_id="job-2",
            snapshot_revision=self.doc.revision,
            status=JobState.COMPLETE,
            candidate_blocks=[
                CandidateBlock(block_id=0, candidate_id=0, rewritten_text="Candidate 0"),
                CandidateBlock(block_id=1, candidate_id=0, rewritten_text="Candidate 1"),
            ],
        )
        self.assertTrue(self.doc.attach_rewrite_result(res))
        self.assertIn(0, self.doc.active_blocks)
        self.assertFalse(self.doc.active_blocks[0].is_accepted)

        # Accept block 0
        self.assertTrue(self.doc.accept_block(0))
        self.assertTrue(self.doc.active_blocks[0].is_accepted)
        self.assertFalse(self.doc.active_blocks[1].is_accepted)

        # Reject/undo acceptance of block 0
        self.assertTrue(self.doc.reject_block(0))
        self.assertFalse(self.doc.active_blocks[0].is_accepted)


if __name__ == "__main__":
    unittest.main()
