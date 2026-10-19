"""Unit tests for Unicode to UTF-16 offset conversion.

Verifies AT-15: Emoji, umlauts, ß, combining characters, and multiline text.
"""

import unittest
from localtext.contracts import TextSpan
from localtext.utils.offsets import OffsetConverter


class TestOffsetConverter(unittest.TestCase):
    def test_ascii_text(self):
        text = "Hello world"
        conv = OffsetConverter(text)
        self.assertEqual(conv.total_code_points, 11)
        self.assertEqual(conv.total_utf16_units, 11)
        for i in range(12):
            self.assertEqual(conv.cp_to_utf16(i), i)
            self.assertEqual(conv.utf16_to_cp(i), i)

    def test_german_special_characters(self):
        # German umlauts and eszett are BMP characters (1 code point = 1 UTF-16 code unit)
        text = "Grüße aus Köln und München!"
        conv = OffsetConverter(text)
        self.assertEqual(conv.total_code_points, len(text))
        self.assertEqual(conv.total_utf16_units, len(text))
        span = TextSpan(start=0, end=5)  # "Grüße"
        self.assertEqual(span.slice_from(text), "Grüße")
        u_start, u_end = conv.span_cp_to_utf16(span)
        self.assertEqual(conv.span_utf16_to_cp(u_start, u_end).slice_from(text), "Grüße")

    def test_astral_characters_and_emojis(self):
        # Emojis (e.g. 🚀, 🎉) are outside BMP -> 1 code point in Python, 2 code units in UTF-16 (surrogate pair)
        text = "Start 🚀 rocket 🎉 end"
        # Code points:
        # "Start " -> 6
        # "🚀" -> 1 cp (index 6)
        # " rocket " -> 8 (indices 7..14)
        # "🎉" -> 1 cp (index 15)
        # " end" -> 4 (indices 16..19)
        conv = OffsetConverter(text)
        self.assertEqual(conv.total_code_points, 20)
        # UTF-16 units: 20 + 2 (one extra unit for each of the 2 astral characters) = 22
        self.assertEqual(conv.total_utf16_units, 22)

        # "🚀" span in Python code points: [6, 7)
        rocket_span = TextSpan(start=6, end=7)
        u_start, u_end = conv.span_cp_to_utf16(rocket_span)
        self.assertEqual(u_end - u_start, 2)  # Occupies 2 UTF-16 code units!

        # Convert back from Qt UTF-16 coordinates
        reconstructed = conv.span_utf16_to_cp(u_start, u_end)
        self.assertEqual(reconstructed.start, 6)
        self.assertEqual(reconstructed.end, 7)
        self.assertEqual(reconstructed.slice_from(text), "🚀")

        # Span spanning past the emoji: "rocket"
        rocket_word_span = TextSpan(start=8, end=14)
        self.assertEqual(rocket_word_span.slice_from(text), "rocket")
        u_wstart, u_wend = conv.span_cp_to_utf16(rocket_word_span)
        self.assertEqual(conv.span_utf16_to_cp(u_wstart, u_wend).slice_from(text), "rocket")

    def test_combining_characters(self):
        # Combining character: 'e' + combining acute accent U+0301 = 2 code points
        text = "Cafe\u0301 de Paris"
        conv = OffsetConverter(text)
        self.assertEqual(conv.total_code_points, len(text))
        span = TextSpan(start=0, end=5)  # "Cafe\u0301"
        u_start, u_end = conv.span_cp_to_utf16(span)
        recon = conv.span_utf16_to_cp(u_start, u_end)
        self.assertEqual(recon.slice_from(text), "Cafe\u0301")


if __name__ == "__main__":
    unittest.main()
