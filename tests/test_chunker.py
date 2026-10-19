"""Unit tests for document chunking and token budgeting.

Verifies APP-09, REP-04, REP-11, and AT-05.
"""

import unittest
from localtext.config import MAX_DISPLAYED_WORDS, MAX_INPUT_BYTES
from localtext.contracts import TextSpan
from localtext.rephrase.chunker import DocumentChunker, ChunkerError


class TestDocumentChunker(unittest.TestCase):
    def setUp(self):
        self.chunker = DocumentChunker(target_chunk_words=300, max_chunk_words=500)

    def test_short_document_creates_single_block(self):
        text = "This is a brief academic document with two sentences. It requires only one block."
        blocks = self.chunker.create_target_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].source_text, text)
        self.assertEqual(blocks[0].context_prefix, "")
        self.assertEqual(blocks[0].context_suffix, "")

    def test_selected_passage_rewriting_with_context(self):
        """REP-04: Selected passage with read-only context."""
        text = "Prefix context sentence. Middle target sentence to be rewritten. Suffix context sentence."
        # Target: "Middle target sentence to be rewritten."
        target_str = "Middle target sentence to be rewritten."
        start = text.index(target_str)
        end = start + len(target_str)
        sel_span = TextSpan(start=start, end=end)

        blocks = self.chunker.create_target_blocks(text, selected_span=sel_span)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].source_text, target_str)
        self.assertIn("Prefix context", blocks[0].context_prefix)
        self.assertIn("Suffix context", blocks[0].context_suffix)

    def test_at05_ten_thousand_word_document(self):
        """AT-05: 10,000-word document chunking, full coverage, no drops, no duplicates."""
        words_list = ["word"] * 20
        paragraph = " ".join(words_list) + ".\n\n"
        # 20 words per paragraph -> 500 paragraphs = 10,000 words
        full_doc = paragraph * 500
        word_count = len(full_doc.split())
        self.assertEqual(word_count, 10_000)

        blocks = self.chunker.create_target_blocks(full_doc)
        self.assertGreater(len(blocks), 1)
        self.assertTrue(self.chunker.verify_coverage(full_doc, blocks))

        # Ensure every block has non-overlapping, strictly increasing spans
        prev_end = 0
        total_covered_words = 0
        for b in blocks:
            self.assertGreaterEqual(b.source_span.start, prev_end)
            prev_end = b.source_span.end
            total_covered_words += len(b.source_text.split())

        self.assertEqual(total_covered_words, 10_000)

    def test_input_limit_exceeded_raises_error(self):
        """APP-09: Over 10,000 words raises ChunkerError."""
        oversized = "word " * 10_005
        with self.assertRaises(ChunkerError):
            self.chunker.validate_document_limits(oversized)


if __name__ == "__main__":
    unittest.main()
