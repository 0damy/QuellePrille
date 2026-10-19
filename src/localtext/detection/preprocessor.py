"""Preprocessor for AI text detection.

Adheres strictly to APP-03, DET-02, DET-03, DET-05, DET-08, AT-03, and AT-04.
Identifies eligible prose spans and explicitly excludes code blocks, tables,
and quotes without mutating the original source string.
Enforces the 150 prose words minimum requirement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple
from localtext.config import DETECTOR_MIN_PROSE_WORDS
from localtext.contracts import DetectorLabel, TextSpan

# Patterns for non-prose content to exclude from detection
EXCLUSION_PATTERNS = {
    # Markdown code fences: ```...```
    "code_fence": re.compile(r"```[\s\S]*?```"),
    # Markdown tables: lines with pipes | ... |
    "markdown_table": re.compile(r"(?:^[ \t]*\|[^\n]+\|[ \t]*\n)+", re.MULTILINE),
    # Blockquotes: lines starting with >
    "blockquote": re.compile(r"(?:^[ \t]*>[^\n]*\n?)+", re.MULTILINE),
    # Raw JSON/XML blocks or extensive code spans
    "indented_code": re.compile(r"(?:^(?: {4}|\t)[^\n]+\n?)+", re.MULTILINE),
}


@dataclass(frozen=True)
class PreprocessResult:
    eligible_spans: List[TextSpan]
    excluded_spans: List[TextSpan]
    eligible_prose_text: str
    word_count: int
    is_sufficient_length: bool
    status_label: DetectorLabel
    message: str


class DetectionPreprocessor:
    """Prepares and validates document text for the detector."""

    def __init__(
        self,
        supported_languages: Tuple[str, ...] = ("en",),
        min_prose_words: int = DETECTOR_MIN_PROSE_WORDS,
    ):
        self.supported_languages = set(lang.lower() for lang in supported_languages)
        self.min_prose_words = min_prose_words

    def validate_language(self, language: str) -> bool:
        """Check if selected language is supported by the active detector profile (APP-03, AT-04)."""
        return language.lower() in self.supported_languages

    def extract_spans(self, text: str, language: str = "en") -> PreprocessResult:
        """Partition original text into eligible prose spans and excluded spans."""
        # 1. Check language support first (AT-04)
        if not self.validate_language(language):
            return PreprocessResult(
                eligible_spans=[],
                excluded_spans=[TextSpan(start=0, end=len(text), label="unsupported_language")],
                eligible_prose_text="",
                word_count=0,
                is_sufficient_length=False,
                status_label=DetectorLabel.UNSUPPORTED_CONTENT,
                message=f"Language '{language}' is not supported by the active detector profile.",
            )

        # 2. Find all excluded spans (code fences, tables, blockquotes)
        raw_excluded: List[TextSpan] = []
        for reason, pat in EXCLUSION_PATTERNS.items():
            for m in pat.finditer(text):
                raw_excluded.append(TextSpan(start=m.start(), end=m.end(), label=reason))

        # Sort and merge overlapping excluded spans
        merged_excluded: List[TextSpan] = []
        if raw_excluded:
            raw_excluded.sort(key=lambda s: s.start)
            curr_s = raw_excluded[0].start
            curr_e = raw_excluded[0].end
            curr_l = raw_excluded[0].label

            for s in raw_excluded[1:]:
                if s.start <= curr_e:
                    curr_e = max(curr_e, s.end)
                else:
                    merged_excluded.append(TextSpan(start=curr_s, end=curr_e, label=curr_l))
                    curr_s = s.start
                    curr_e = s.end
                    curr_l = s.label
            merged_excluded.append(TextSpan(start=curr_s, end=curr_e, label=curr_l))

        # 3. Invert excluded spans to obtain eligible prose spans
        eligible_spans: List[TextSpan] = []
        last_idx = 0
        for exc in merged_excluded:
            if exc.start > last_idx:
                chunk = text[last_idx : exc.start]
                if chunk.strip():
                    eligible_spans.append(TextSpan(start=last_idx, end=exc.start, label="prose"))
            last_idx = exc.end

        if last_idx < len(text):
            chunk = text[last_idx:]
            if chunk.strip():
                eligible_spans.append(TextSpan(start=last_idx, end=len(text), label="prose"))

        # 4. Count eligible prose words
        prose_pieces = [sp.slice_from(text) for sp in eligible_spans]
        combined_prose = " ".join(prose_pieces)
        words = len(combined_prose.split())

        # 5. Check minimum word count (DET-03, AT-03)
        if words < self.min_prose_words:
            return PreprocessResult(
                eligible_spans=eligible_spans,
                excluded_spans=merged_excluded,
                eligible_prose_text=combined_prose,
                word_count=words,
                is_sufficient_length=False,
                status_label=DetectorLabel.INSUFFICIENT_TEXT,
                message=(
                    f"Input contains only {words} eligible prose words. "
                    f"The detector requires at least {self.min_prose_words} words for reliable scoring."
                ),
            )

        return PreprocessResult(
            eligible_spans=eligible_spans,
            excluded_spans=merged_excluded,
            eligible_prose_text=combined_prose,
            word_count=words,
            is_sufficient_length=True,
            status_label=DetectorLabel.UNCERTAIN,  # Provisional until scored
            message=f"Eligible prose: {words} words across {len(eligible_spans)} spans.",
        )
