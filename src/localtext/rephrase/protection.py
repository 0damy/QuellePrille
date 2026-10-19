"""Text protection engine: detects, freezes, masks, and restores immutable text spans.

Adheres strictly to REP-05, REP-06, AT-06, and AT-16.
Resolves overlapping spans deterministically: longer spans take precedence,
preventing nested markers and replacement collisions.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple
from localtext.contracts import ProtectedSpan, TextSpan

# Regex patterns for automatic entity detection (REP-06, AT-06)
PATTERNS = {
    # LaTeX citations: \cite{key}, \citep{key}, \citet{key1,key2}
    "latex_citation": re.compile(r"\\cite[pt]?\{[^}]+\}"),
    # Bracketed numeric/alphanumeric citations: [1], [12, 13], [Pohle2020]
    "bracket_citation": re.compile(r"\[(?:[0-9]+|[A-Za-z]+[0-9]{2,4})(?:[;,]\s*(?:[0-9]+|[A-Za-z]+[0-9]{2,4}))*\]"),
    # URLs: http:// or https://
    "url": re.compile(r"https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&/=]*)"),
    # Emails
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # Inline code: `foo()`, `variable_name`
    "inline_code": re.compile(r"`[^`\n]+`"),
    # Mathematical equations / LaTeX formulas: $...$ or $$...$$
    "math_formula": re.compile(r"\$\$?[^\$\n]+\$\$?"),
    # Quantities with units or percentages: 3.5%, 48 km, 1.234,50 EUR, 100 kg, 20 ms
    "quantity_unit": re.compile(
        r"\b\d+(?:[.,]\d+)?\s*(?:%|km|m|cm|mm|kg|g|mg|s|ms|h|min|EUR|USD|\$|€|£|bps|Gbps|MB|GB|TB|KiB|MiB|GiB)\b"
    ),
    # Numbers with decimals/localized commas: e.g. 1,000.50 or 1.000,50
    "formatted_number": re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\b"),
}


class ProtectionEngine:
    """Detects, masks, and verifies protected spans within source text."""

    def __init__(self, placeholder_template: str = "⟦PROT_{id}⟧"):
        self.placeholder_template = placeholder_template

    def detect_auto_protected_spans(self, text: str) -> List[ProtectedSpan]:
        """Automatically find citations, code, URLs, emails, formulas, and quantities."""
        spans: List[ProtectedSpan] = []
        for reason, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                start, end = match.span()
                matched_str = text[start:end]
                spans.append(
                    ProtectedSpan(
                        span=TextSpan(start=start, end=end, label=reason),
                        original_text=matched_str,
                        reason=reason,
                    )
                )
        return spans

    def freeze_words_or_phrases(
        self, text: str, phrases: List[str]
    ) -> List[ProtectedSpan]:
        """Freeze exact occurrences of user-selected words or phrases (REP-05, AT-16)."""
        spans: List[ProtectedSpan] = []
        for phrase in phrases:
            if not phrase:
                continue
            # Exact occurrence search preserving case and word boundaries where appropriate
            escaped = re.escape(phrase)
            pattern = re.compile(rf"{escaped}")
            for match in pattern.finditer(text):
                start, end = match.span()
                spans.append(
                    ProtectedSpan(
                        span=TextSpan(start=start, end=end, label="user_freeze"),
                        original_text=text[start:end],
                        reason="user_freeze",
                    )
                )
        return spans

    def resolve_overlaps(self, spans: List[ProtectedSpan]) -> List[ProtectedSpan]:
        """Deterministically resolve overlaps: longer spans take precedence.

        If lengths are equal, earlier spans take precedence (AT-16).
        Prevents nested or intersecting markers.
        """
        if not spans:
            return []

        # Sort: descending by span length, then ascending by start offset
        sorted_spans = sorted(
            spans,
            key=lambda p: (-(p.span.end - p.span.start), p.span.start),
        )

        resolved: List[ProtectedSpan] = []
        occupied_indices: Set[int] = set()

        for candidate in sorted_spans:
            c_range = set(range(candidate.span.start, candidate.span.end))
            # Check for any overlap with already accepted spans
            if not (occupied_indices & c_range):
                occupied_indices.update(c_range)
                resolved.append(candidate)

        # Sort final list ascending by start offset for consistent left-to-right processing
        return sorted(resolved, key=lambda p: p.span.start)

    def mask_text(
        self, text: str, protected_spans: List[ProtectedSpan]
    ) -> Tuple[str, List[ProtectedSpan]]:
        """Replace protected spans with collision-resistant placeholders.

        Returns masked text and the ordered list of ProtectedSpans with assigned placeholders.
        """
        resolved = self.resolve_overlaps(protected_spans)
        if not resolved:
            return text, []

        pieces: List[str] = []
        last_idx = 0
        masked_spans: List[ProtectedSpan] = []

        for idx, item in enumerate(resolved):
            pieces.append(text[last_idx : item.span.start])
            placeholder = self.placeholder_template.format(id=idx)
            pieces.append(placeholder)
            masked_spans.append(
                ProtectedSpan(
                    span=item.span,
                    original_text=item.original_text,
                    reason=item.reason,
                    placeholder=placeholder,
                )
            )
            last_idx = item.span.end

        pieces.append(text[last_idx:])
        return "".join(pieces), masked_spans

    def unmask_text(
        self, masked_text: str, masked_spans: List[ProtectedSpan]
    ) -> Tuple[str, List[str]]:
        """Restore protected content into masked text.

        Returns (unmasked_text, list_of_errors).
        If any assigned placeholder is missing or duplicated, logs a validation failure.
        Never restores unknown placeholders.
        """
        errors: List[str] = []
        result = masked_text

        # First verify each expected placeholder is present exactly once
        for item in masked_spans:
            if not item.placeholder:
                continue
            count = result.count(item.placeholder)
            if count == 0:
                errors.append(
                    f"Protected placeholder {item.placeholder} ('{item.original_text}') was omitted from output."
                )
            elif count > 1:
                errors.append(
                    f"Protected placeholder {item.placeholder} ('{item.original_text}') was duplicated {count} times."
                )

        if errors:
            return result, errors

        # Restore placeholders
        for item in masked_spans:
            if item.placeholder:
                result = result.replace(item.placeholder, item.original_text)

        # Check if any stray/unknown placeholder remains in output
        stray = re.findall(r"⟦PROT_\d+⟧", result)
        if stray:
            errors.append(f"Output contains unrecognized protected marker: {stray}")

        return result, errors
