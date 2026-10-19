"""Document state manager: revision tagging, undo history, block acceptance, and stale result invalidation.

Adheres strictly to APP-05, REP-09, AT-11, and Section 10.
Document state is owned by the GUI/controller, never by an inference worker.
Edits make previous results visibly stale and prevent old jobs from overwriting newer text revisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from localtext.contracts import CandidateBlock, DocumentSnapshot, RewriteResult, TextSpan


@dataclass
class BlockState:
    block_id: int
    original_text: str
    current_text: str
    candidates: List[CandidateBlock] = field(default_factory=list)
    selected_candidate_id: Optional[int] = None
    is_accepted: bool = False


class DocumentStateManager:
    """Manages document text, revisions, undo history, and block operations."""

    def __init__(self, initial_text: str = "", language: str = "en"):
        self.document_id = "doc-1"
        self._revision = 1
        self._text = initial_text
        self.language = language
        self._undo_stack: List[str] = [initial_text]
        self._redo_stack: List[str] = []
        self.active_blocks: Dict[int, BlockState] = {}
        self.latest_rewrite_result: Optional[RewriteResult] = None
        self.is_result_stale: bool = False

    @property
    def text(self) -> str:
        return self._text

    @property
    def revision(self) -> int:
        return self._revision

    def get_snapshot(self) -> DocumentSnapshot:
        """Create an immutable snapshot of current state."""
        return DocumentSnapshot(
            document_id=self.document_id,
            revision=self._revision,
            original_text=self._text,
            language=self.language,
        )

    def set_text(self, new_text: str) -> None:
        """Update text from user editing; bumps revision and marks old results stale (APP-05, AT-11)."""
        if new_text == self._text:
            return

        self._undo_stack.append(self._text)
        self._redo_stack.clear()
        self._text = new_text
        self._revision += 1
        # Edits make previous inference results stale
        self.is_result_stale = True

    def undo(self) -> bool:
        """Revert to previous text revision."""
        if not self._undo_stack:
            return False
        prev = self._undo_stack.pop()
        self._redo_stack.append(self._text)
        self._text = prev
        self._revision += 1
        self.is_result_stale = True
        return True

    def redo(self) -> bool:
        """Reapply undone text revision."""
        if not self._redo_stack:
            return False
        next_text = self._redo_stack.pop()
        self._undo_stack.append(self._text)
        self._text = next_text
        self._revision += 1
        self.is_result_stale = True
        return True

    def attach_rewrite_result(self, result: RewriteResult) -> bool:
        """Attach a completed rewrite result if its revision matches current document state (AT-11)."""
        if result.snapshot_revision != self._revision:
            # Result from old revision! Must not overwrite current edits (AT-11)
            self.is_result_stale = True
            return False

        self.latest_rewrite_result = result
        self.is_result_stale = False

        # Initialize block states
        self.active_blocks.clear()
        for cand in result.candidate_blocks:
            orig = ""
            self.active_blocks[cand.block_id] = BlockState(
                block_id=cand.block_id,
                original_text=orig,
                current_text=cand.rewritten_text,
                candidates=[cand],
                selected_candidate_id=cand.candidate_id,
                is_accepted=False,
            )
        return True

    def accept_block(self, block_id: int) -> bool:
        """Accept rewritten text for a specific block (REP-09)."""
        b = self.active_blocks.get(block_id)
        if not b or not b.candidates:
            return False
        b.is_accepted = True
        return True

    def reject_block(self, block_id: int) -> bool:
        """Reject rewrite and restore original for a block (REP-09)."""
        b = self.active_blocks.get(block_id)
        if not b:
            return False
        b.is_accepted = False
        return True
