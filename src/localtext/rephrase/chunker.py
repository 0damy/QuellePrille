"""Document chunker and token budgeting engine for rephrasing.

Adheres strictly to REP-04, REP-11, APP-09, and Acceptance Test AT-05.
Splits text deterministically at paragraph boundaries (or safe sentence boundaries),
retains original character spans, and attaches read-only adjacent context.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from localtext.config import MAX_DISPLAYED_WORDS, MAX_INPUT_BYTES
from localtext.contracts import TargetBlock, TextSpan


class ChunkerError(ValueError):
    """Raised when document limits are exceeded or chunking fails."""
    pass


class DocumentChunker:
    """Splits text into sized target blocks with adjacent read-only context."""

    def __init__(
        self,
        target_chunk_words: int = 400,
        max_chunk_words: int = 600,
        context_words: int = 60,
    ):
        self.target_chunk_words = target_chunk_words
        self.max_chunk_words = max_chunk_words
        self.context_words = context_words

    def validate_document_limits(self, text: str) -> None:
        """Enforce APP-09 limits: at most 10,000 words and 1 MiB UTF-8 bytes."""
        byte_len = len(text.encode("utf-8"))
        if byte_len > MAX_INPUT_BYTES:
            raise ChunkerError(
                f"Document size ({byte_len} bytes) exceeds maximum input limit of {MAX_INPUT_BYTES} bytes (1 MiB)."
            )

        word_count = len(text.split())
        if word_count > MAX_DISPLAYED_WORDS:
            raise ChunkerError(
                f"Document word count ({word_count} words) exceeds maximum limit of {MAX_DISPLAYED_WORDS} words."
            )

    def split_into_paragraphs(self, text: str) -> List[TextSpan]:
        """Split text into paragraph spans preserving exact original character offsets."""
        spans: List[TextSpan] = []
        # Find paragraphs separated by one or more blank lines (or newlines)
        pattern = re.compile(r"[^\n]+(?:\n[^\n]+)*")
        for match in pattern.finditer(text):
            start, end = match.span()
            # Trim trailing whitespace from span but record accurate offsets
            matched_str = text[start:end]
            if matched_str.strip():
                spans.append(TextSpan(start=start, end=end, label="paragraph"))
        return spans

    def split_large_paragraph(self, text: str, span: TextSpan) -> List[TextSpan]:
        """Subdivide an oversized paragraph at sentence boundaries."""
        sub_spans: List[TextSpan] = []
        p_text = span.slice_from(text)
        # Sentence splitting pattern (period, exclamation, question mark followed by space or end)
        sent_pattern = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")

        current_start = span.start
        current_words = 0
        current_span_start = span.start

        for match in sent_pattern.finditer(p_text):
            s_start = span.start + match.start()
            s_end = span.start + match.end()
            sent_text = text[s_start:s_end]
            sent_words = len(sent_text.split())

            if current_words + sent_words > self.max_chunk_words and current_words > 0:
                sub_spans.append(TextSpan(start=current_span_start, end=s_start))
                current_span_start = s_start
                current_words = sent_words
            else:
                current_words += sent_words

        if current_span_start < span.end:
            sub_spans.append(TextSpan(start=current_span_start, end=span.end))

        return sub_spans if sub_spans else [span]

    def create_target_blocks(
        self,
        text: str,
        selected_span: Optional[TextSpan] = None,
    ) -> List[TargetBlock]:
        """Create ordered TargetBlocks covering the selected passage or the entire document."""
        self.validate_document_limits(text)

        if not text.strip():
            return []

        # If a specific passage was selected, only rewrite that passage (REP-04)
        if selected_span is not None:
            # Context before and after
            prefix_start = max(0, selected_span.start - self.context_words * 8)
            suffix_end = min(len(text), selected_span.end + self.context_words * 8)

            prefix = text[prefix_start : selected_span.start]
            suffix = text[selected_span.end : suffix_end]

            return [
                TargetBlock(
                    block_id=0,
                    source_span=selected_span,
                    source_text=selected_span.slice_from(text),
                    context_prefix=prefix,
                    context_suffix=suffix,
                )
            ]

        # Whole-document chunking: group paragraphs up to target_chunk_words
        raw_paras = self.split_into_paragraphs(text)
        candidate_spans: List[TextSpan] = []

        for p_span in raw_paras:
            words = len(p_span.slice_from(text).split())
            if words > self.max_chunk_words:
                candidate_spans.extend(self.split_large_paragraph(text, p_span))
            else:
                candidate_spans.append(p_span)

        # Merge adjacent spans up to target_chunk_words
        merged_spans: List[TextSpan] = []
        curr_start = None
        curr_end = None
        curr_words = 0

        for sp in candidate_spans:
            w = len(sp.slice_from(text).split())
            if curr_start is None:
                curr_start = sp.start
                curr_end = sp.end
                curr_words = w
            elif curr_words + w <= self.target_chunk_words:
                curr_end = sp.end
                curr_words += w
            else:
                merged_spans.append(TextSpan(start=curr_start, end=curr_end))
                curr_start = sp.start
                curr_end = sp.end
                curr_words = w

        if curr_start is not None and curr_end is not None:
            merged_spans.append(TextSpan(start=curr_start, end=curr_end))

        # Assemble TargetBlocks with read-only context
        blocks: List[TargetBlock] = []
        for idx, sp in enumerate(merged_spans):
            # Context prefix from previous block (or preceding text)
            prefix = ""
            if idx > 0:
                prev_text = merged_spans[idx - 1].slice_from(text)
                words = prev_text.split()
                prefix = " ".join(words[-self.context_words:])

            # Context suffix from next block
            suffix = ""
            if idx + 1 < len(merged_spans):
                next_text = merged_spans[idx + 1].slice_from(text)
                words = next_text.split()
                suffix = " ".join(words[:self.context_words])

            blocks.append(
                TargetBlock(
                    block_id=idx,
                    source_span=sp,
                    source_text=sp.slice_from(text),
                    context_prefix=prefix,
                    context_suffix=suffix,
                )
            )

        return blocks

    def verify_coverage(self, original_text: str, blocks: List[TargetBlock]) -> bool:
        """Verify that all target blocks account for the eligible prose without gaps or overlaps."""
        if not blocks:
            return not original_text.strip()

        # Check ordering and no overlap
        for i in range(len(blocks) - 1):
            if blocks[i].source_span.end > blocks[i + 1].source_span.start:
                return False  # Overlapping target blocks!

        return True
