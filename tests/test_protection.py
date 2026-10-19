"""Unit tests for text protection and preservation.

Verifies REP-05, REP-06, AT-06, and AT-16.
"""

import unittest
from localtext.contracts import ProtectedSpan, TextSpan
from localtext.rephrase.protection import ProtectionEngine


class TestProtectionEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ProtectionEngine()

    def test_at06_protected_entities(self):
        """AT-06: Protected HZD, 3.5%, 48 km, [12], \\cite{pohle2020}, email, and inline code."""
        text = (
            "We measured HZD with an error rate of 3.5% across 48 km, "
            "as described in [12] and \\cite{pohle2020}. "
            "Contact author@uni-koeln.de or inspect `eval_script()`."
        )

        auto_spans = self.engine.detect_auto_protected_spans(text)
        # User explicitly freezes "HZD"
        user_spans = self.engine.freeze_words_or_phrases(text, ["HZD"])

        all_spans = auto_spans + user_spans
        masked_text, masked_items = self.engine.mask_text(text, all_spans)

        # Verify that all target entities were masked
        self.assertNotIn("HZD", masked_text)
        self.assertNotIn("3.5%", masked_text)
        self.assertNotIn("48 km", masked_text)
        self.assertNotIn("[12]", masked_text)
        self.assertNotIn("\\cite{pohle2020}", masked_text)
        self.assertNotIn("author@uni-koeln.de", masked_text)
        self.assertNotIn("`eval_script()`", masked_text)

        # Unmask and verify 100% exact verbatim restoration
        unmasked, errors = self.engine.unmask_text(masked_text, masked_items)
        self.assertEqual(errors, [])
        self.assertEqual(unmasked, text)

    def test_at16_overlapping_terms_and_precedence(self):
        """AT-16: Freeze repeated terms, overlapping terms; longer span takes precedence."""
        text = "Deep learning and deep reinforcement learning are active fields."
        # User freezes both "learning" and "deep reinforcement learning"
        user_spans = self.engine.freeze_words_or_phrases(
            text, ["learning", "deep reinforcement learning"]
        )
        resolved = self.engine.resolve_overlaps(user_spans)

        # "deep reinforcement learning" must win over "learning" inside it
        texts_in_resolved = [p.original_text for p in resolved]
        self.assertIn("deep reinforcement learning", texts_in_resolved)
        # "learning" at the end of "Deep learning" is separate, so it should also exist
        self.assertEqual(texts_in_resolved.count("learning"), 1)

        masked_text, masked_items = self.engine.mask_text(text, user_spans)
        unmasked, errors = self.engine.unmask_text(masked_text, masked_items)
        self.assertEqual(errors, [])
        self.assertEqual(unmasked, text)

    def test_omitted_placeholder_detection(self):
        """Verify that an omitted placeholder fails unmasking with a clear error."""
        text = "Important term [10] must be preserved."
        spans = self.engine.detect_auto_protected_spans(text)
        masked_text, masked_items = self.engine.mask_text(text, spans)

        # Simulate bad model output that dropped the placeholder
        corrupted_output = "Important term was dropped."
        _, errors = self.engine.unmask_text(corrupted_output, masked_items)
        self.assertGreater(len(errors), 0)
        self.assertIn("omitted", errors[0])

    def test_duplicated_placeholder_detection(self):
        """Verify that a duplicated placeholder fails unmasking."""
        text = "Value is 50 kg."
        spans = self.engine.detect_auto_protected_spans(text)
        masked_text, masked_items = self.engine.mask_text(text, spans)

        # Simulate model duplicating placeholder
        placeholder = masked_items[0].placeholder
        corrupted_output = f"Value is {placeholder} and also {placeholder}."
        _, errors = self.engine.unmask_text(corrupted_output, masked_items)
        self.assertGreater(len(errors), 0)
        self.assertIn("duplicated", errors[0])


if __name__ == "__main__":
    unittest.main()
