"""Bidirectional offset conversions between Python Unicode code points and Qt UTF-16 code units.

Addresses Section 10 and Acceptance Test AT-15.
In Python, strings are sequences of Unicode code points (characters).
In Qt (QTextDocument, QTextCursor), string positions and selections are measured
in UTF-16 code units (where characters outside BMP like emoji occupy 2 units as surrogate pairs).
"""

from __future__ import annotations

from typing import List, Tuple
from localtext.contracts import TextSpan


class OffsetConverter:
    """Precomputed mapping table between Unicode code points and UTF-16 code units for a string."""

    def __init__(self, text: str):
        self.text = text
        # Compute forward and backward offset maps
        # cp_to_utf16[i] gives UTF-16 code unit index of Unicode code point i
        self._cp_to_utf16: List[int] = []
        # utf16_to_cp[u] gives Unicode code point index corresponding to UTF-16 unit u
        self._utf16_to_cp: List[int] = []

        utf16_unit = 0
        for cp_idx, char in enumerate(text):
            self._cp_to_utf16.append(utf16_unit)
            # Encode single character to UTF-16-LE bytes to determine unit count
            units = len(char.encode("utf-16-le")) // 2
            for _ in range(units):
                self._utf16_to_cp.append(cp_idx)
            utf16_unit += units

        # Append sentinel for the end of the string
        self._cp_to_utf16.append(utf16_unit)
        self._utf16_to_cp.append(len(text))

    @property
    def total_code_points(self) -> int:
        return len(self.text)

    @property
    def total_utf16_units(self) -> int:
        return self._cp_to_utf16[-1]

    def cp_to_utf16(self, cp_offset: int) -> int:
        """Convert a Unicode code point offset to a UTF-16 code unit offset."""
        if cp_offset < 0:
            return 0
        if cp_offset >= len(self._cp_to_utf16):
            return self._cp_to_utf16[-1]
        return self._cp_to_utf16[cp_offset]

    def utf16_to_cp(self, utf16_offset: int) -> int:
        """Convert a UTF-16 code unit offset to a Unicode code point offset."""
        if utf16_offset < 0:
            return 0
        if utf16_offset >= len(self._utf16_to_cp):
            return self._utf16_to_cp[-1]
        return self._utf16_to_cp[utf16_offset]

    def span_cp_to_utf16(self, span: TextSpan) -> Tuple[int, int]:
        """Convert a TextSpan in Unicode code points to a (start, end) tuple in UTF-16 units."""
        return self.cp_to_utf16(span.start), self.cp_to_utf16(span.end)

    def span_utf16_to_cp(self, utf16_start: int, utf16_end: int, label: str = "") -> TextSpan:
        """Convert a (start, end) range in UTF-16 units to a TextSpan in Unicode code points."""
        cp_start = self.utf16_to_cp(utf16_start)
        cp_end = self.utf16_to_cp(utf16_end)
        return TextSpan(start=cp_start, end=cp_end, label=label)
