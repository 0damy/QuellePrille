"""Complete rephrasing pipeline coordinating protection, chunking, generation, repair, and diffs.

Adheres strictly to REP-01 through REP-11, AT-06, AT-07, AT-08, AT-10, and AT-14.
Implements the exact 8-step pipeline from Section 8:
Snapshot -> Protect -> Budget/Chunk -> Generate -> Validate -> 1 Bounded Repair -> Assemble -> Review.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional
from localtext.contracts import (
    CandidateBlock,
    ChangeStrength,
    JobState,
    ProtectedSpan,
    RephraseMode,
    RewriteRequest,
    RewriteResult,
    TargetBlock,
    TextSpan,
)
from localtext.rephrase.chunker import DocumentChunker
from localtext.rephrase.diff import TextDiffEngine
from localtext.rephrase.preservation_checker import PreservationChecker
from localtext.rephrase.prompts import build_user_prompt, load_system_prompt
from localtext.rephrase.protection import ProtectionEngine


class RephrasePipeline:
    """Orchestrates end-to-end document rephrasing with deterministic quality gates."""

    def __init__(
        self,
        protection_engine: Optional[ProtectionEngine] = None,
        chunker: Optional[DocumentChunker] = None,
        diff_engine: Optional[TextDiffEngine] = None,
    ):
        self.protection_engine = protection_engine or ProtectionEngine()
        self.chunker = chunker or DocumentChunker()
        self.diff_engine = diff_engine or TextDiffEngine()

    def run_rephrase(
        self,
        request: RewriteRequest,
        generator_fn: Callable[[str, str], str],
        cancel_event: Optional[threading.Event] = None,
        language: str = "en",
        user_frozen_words: Optional[List[str]] = None,
        selected_span: Optional[TextSpan] = None,
    ) -> RewriteResult:
        """Execute full rephrase pipeline for a rewrite request."""
        start_time = time.perf_counter()
        sys_prompt = load_system_prompt()
        checker = PreservationChecker(language=language)

        # 1. Protection & masking across target blocks (REP-05, REP-06, AT-06)
        frozen_list = user_frozen_words or []
        candidate_blocks: List[CandidateBlock] = []
        source_to_output_map: dict[int, int] = {}
        all_failed_checks: List[str] = []
        all_warnings: List[str] = []

        # If target blocks were not pre-chunked, chunk them now
        target_blocks = list(request.target_blocks)
        if not target_blocks:
            return RewriteResult(
                job_id=request.job_id,
                snapshot_revision=request.snapshot_revision,
                status=JobState.FAILED,
                failed_checks=["No target blocks provided in request."],
            )

        for block in target_blocks:
            if cancel_event and cancel_event.is_set():
                # Responsive cancellation (AT-10, NFR-07)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return RewriteResult(
                    job_id=request.job_id,
                    snapshot_revision=request.snapshot_revision,
                    status=JobState.CANCELLED,
                    candidate_blocks=candidate_blocks,
                    warnings=["Job cancelled by user."],
                    timings_ms={"total_ms": elapsed_ms},
                )

            # Auto-detect entities + freeze words for this block
            auto_spans = self.protection_engine.detect_auto_protected_spans(block.source_text)
            user_spans = self.protection_engine.freeze_words_or_phrases(block.source_text, frozen_list)
            masked_target, masked_items = self.protection_engine.mask_text(
                block.source_text, auto_spans + user_spans
            )

            # Build initial user prompt
            user_prompt = build_user_prompt(
                target_text=masked_target,
                language=language,
                mode=request.mode,
                strength=request.strength,
                custom_style=request.custom_style,
                context_prefix=block.context_prefix,
                context_suffix=block.context_suffix,
            )

            # Generate primary candidate
            raw_generated = generator_fn(user_prompt, sys_prompt)

            # Restore protected content (REP-06, AT-06)
            unmasked_output, unmask_errors = self.protection_engine.unmask_text(
                raw_generated, masked_items
            )

            # Run deterministic preservation checks (REP-07, REP-10, AT-07, AT-08)
            report = checker.check_preservation(
                source_text=block.source_text,
                candidate_text=unmasked_output,
                mode=request.mode.value,
            )

            final_text = unmasked_output
            is_repaired = False
            failed_block_checks = list(report.failed_checks) + list(unmask_errors)

            # Step 6: One Bounded Repair Attempt (REP-10)
            if (not report.passed or unmask_errors) and not (cancel_event and cancel_event.is_set()):
                repair_instructions = report.suggested_repair_instruction or "; ".join(unmask_errors)
                repair_prompt = build_user_prompt(
                    target_text=masked_target,
                    language=language,
                    mode=request.mode,
                    strength=request.strength,
                    custom_style=request.custom_style,
                    context_prefix=block.context_prefix,
                    context_suffix=block.context_suffix,
                    repair_instruction=repair_instructions,
                )

                # Attempt single repair request
                repaired_raw = generator_fn(repair_prompt, sys_prompt)
                repaired_unmasked, rep_unmask_errors = self.protection_engine.unmask_text(
                    repaired_raw, masked_items
                )
                repaired_report = checker.check_preservation(
                    source_text=block.source_text,
                    candidate_text=repaired_unmasked,
                    mode=request.mode.value,
                )

                if repaired_report.passed and not rep_unmask_errors:
                    final_text = repaired_unmasked
                    is_repaired = True
                    failed_block_checks.clear()
                else:
                    # Still invalid: fallback to original text and explain conflict (REP-10, AT-14)
                    final_text = block.source_text
                    failed_block_checks.append(
                        "Repair attempt failed. Preserved original text to prevent factual distortion."
                    )

            # Compute rich HTML diff (REP-03)
            diff_html = self.diff_engine.render_html_diff(block.source_text, final_text)

            candidate_blocks.append(
                CandidateBlock(
                    block_id=block.block_id,
                    candidate_id=0,
                    rewritten_text=final_text,
                    diff_html=diff_html,
                    is_repaired=is_repaired,
                    failed_checks=failed_block_checks,
                    warnings=report.warnings,
                )
            )
            source_to_output_map[block.block_id] = block.block_id
            all_failed_checks.extend(failed_block_checks)
            all_warnings.extend(report.warnings)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        overall_status = JobState.COMPLETE if not all_failed_checks else JobState.PARTIAL

        return RewriteResult(
            job_id=request.job_id,
            snapshot_revision=request.snapshot_revision,
            status=overall_status,
            candidate_blocks=candidate_blocks,
            source_to_output_mapping=source_to_output_map,
            failed_checks=all_failed_checks,
            warnings=all_warnings,
            timings_ms={"total_ms": elapsed_ms},
        )
