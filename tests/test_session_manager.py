"""Unit tests for session persistence and privacy guarantees.

Verifies APP-07 and Acceptance Test AT-18:
- Zero implicit document persistence.
- Restart after explicit session save restores only explicitly saved content.
- Clean session clearing.
"""

import tempfile
import unittest
from pathlib import Path
from localtext.storage.session_manager import SessionManager


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mgr = SessionManager(session_filename="test_session.json")
        # Direct session file to test temp dir
        self.mgr.session_file = Path(self.temp_dir.name) / "test_session.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_at18_session_explicit_save_and_restore(self):
        # 1. By default, no session exists
        self.assertFalse(self.mgr.has_saved_session())
        self.assertIsNone(self.mgr.load_session())

        # 2. Explicit save
        self.mgr.save_session(
            text="Explicitly saved document draft.",
            language="de",
            active_mode="academic",
            model_profile_id="qwen-9b-q6k",
        )
        self.assertTrue(self.mgr.has_saved_session())

        # 3. Simulate application restart
        new_mgr = SessionManager(session_filename="test_session.json")
        new_mgr.session_file = self.mgr.session_file
        restored = new_mgr.load_session()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.text, "Explicitly saved document draft.")
        self.assertEqual(restored.language, "de")
        self.assertEqual(restored.active_mode, "academic")
        self.assertEqual(restored.model_profile_id, "qwen-9b-q6k")

        # 4. Clear session
        new_mgr.clear_session()
        self.assertFalse(new_mgr.has_saved_session())
        self.assertIsNone(new_mgr.load_session())


if __name__ == "__main__":
    unittest.main()
