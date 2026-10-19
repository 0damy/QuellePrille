"""Unit tests for word-level difference generation.

Verifies REP-03.
"""

import unittest
from localtext.rephrase.diff import TextDiffEngine


class TestTextDiffEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TextDiffEngine()

    def test_identical_text_has_no_changes(self):
        text = "This is a clean sentence."
        html_out = self.engine.render_html_diff(text, text)
        self.assertNotIn("<del>", html_out)
        self.assertNotIn("<ins>", html_out)
        self.assertEqual(html_out, text)

    def test_word_replacement_diff(self):
        src = "The quick brown fox jumps."
        tgt = "The fast brown fox leaps."
        html_out = self.engine.render_html_diff(src, tgt)
        self.assertIn("<del", html_out)
        self.assertIn("quick", html_out)
        self.assertIn("<ins", html_out)
        self.assertIn("fast", html_out)
        self.assertIn("leaps", html_out)


if __name__ == "__main__":
    unittest.main()
