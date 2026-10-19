"""Word-level and character-level difference generator for side-by-side editing.

Adheres strictly to REP-03 and APP-08.
Produces accessible, tagged markup with non-color indicators (strike-through and underline)
suitable for rich text display in Qt and web export.
"""

from __future__ import annotations

import difflib
import html
import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class DiffBlock:
    tag: str  # 'equal', 'replace', 'insert', 'delete'
    source_chunk: str
    target_chunk: str


class TextDiffEngine:
    """Computes word-level and token-level diffs between source and rewrite."""

    def tokenize_words_and_spaces(self, text: str) -> List[str]:
        """Split text into words and whitespace/punctuation preserving all characters."""
        return re.findall(r"\w+|\s+|[^\w\s]", text, re.UNICODE)

    def compute_diff_blocks(self, source_text: str, target_text: str) -> List[DiffBlock]:
        src_tokens = self.tokenize_words_and_spaces(source_text)
        tgt_tokens = self.tokenize_words_and_spaces(target_text)

        matcher = difflib.SequenceMatcher(None, src_tokens, tgt_tokens)
        blocks: List[DiffBlock] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            src_str = "".join(src_tokens[i1:i2])
            tgt_str = "".join(tgt_tokens[j1:j2])
            blocks.append(DiffBlock(tag=tag, source_chunk=src_str, target_chunk=tgt_str))

        return blocks

    def render_html_diff(self, source_text: str, target_text: str) -> str:
        """Render accessible HTML diff with visual and semantic styling (REP-03, APP-08)."""
        blocks = self.compute_diff_blocks(source_text, target_text)
        html_parts: List[str] = []

        for b in blocks:
            if b.tag == "equal":
                html_parts.append(html.escape(b.target_chunk))
            elif b.tag == "insert":
                html_parts.append(
                    f'<ins style="background-color: #d4edda; color: #155724; text-decoration: underline;">{html.escape(b.target_chunk)}</ins>'
                )
            elif b.tag == "delete":
                html_parts.append(
                    f'<del style="background-color: #f8d7da; color: #721c24; text-decoration: line-through;">{html.escape(b.source_chunk)}</del>'
                )
            elif b.tag == "replace":
                html_parts.append(
                    f'<del style="background-color: #f8d7da; color: #721c24; text-decoration: line-through;">{html.escape(b.source_chunk)}</del>'
                    f'<ins style="background-color: #d4edda; color: #155724; text-decoration: underline;">{html.escape(b.target_chunk)}</ins>'
                )

        return "".join(html_parts)
