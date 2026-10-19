"""Token windowing and coverage-weighted logit aggregation for AI text detection.

Adheres strictly to Section 9, DET-05, and DET-06.
Computes token-coverage weighted document logits:
  c_i = number of windows covering eligible source token i
  w_j = sum_{i in window j} (1 / c_i)
  z_document = sum(w_j * z_j) / sum(w_j)
Never truncates silently to the first 512 tokens.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from localtext.contracts import PassageScore, TextSpan


@dataclass(frozen=True)
class WindowSpec:
    window_id: int
    token_indices: List[int]
    char_span: TextSpan
    coverage_weight: float = 1.0


class DocumentAggregator:
    """Partitions tokenized prose into overlapping windows and computes weighted document logits."""

    def __init__(self, max_window_tokens: int = 512, overlap_tokens: int = 64):
        self.max_window_tokens = max_window_tokens
        self.overlap_tokens = overlap_tokens

    def create_windows(
        self,
        token_count: int,
        token_to_char_offsets: Optional[List[Tuple[int, int]]] = None,
    ) -> List[WindowSpec]:
        """Generate overlapping window slices covering all source tokens without truncation (DET-05)."""
        if token_count <= 0:
            return []

        stride = max(1, self.max_window_tokens - self.overlap_tokens)
        windows: List[WindowSpec] = []
        start_idx = 0
        window_id = 0

        while start_idx < token_count:
            end_idx = min(token_count, start_idx + self.max_window_tokens)
            t_indices = list(range(start_idx, end_idx))

            if token_to_char_offsets and start_idx < len(token_to_char_offsets):
                c_start = token_to_char_offsets[start_idx][0]
                c_end = token_to_char_offsets[end_idx - 1][1]
                char_span = TextSpan(start=c_start, end=c_end, label=f"window_{window_id}")
            else:
                char_span = TextSpan(start=start_idx, end=end_idx, label=f"window_{window_id}")

            windows.append(
                WindowSpec(
                    window_id=window_id,
                    token_indices=t_indices,
                    char_span=char_span,
                )
            )

            window_id += 1
            if end_idx >= token_count:
                break
            start_idx += stride

        return windows

    def compute_coverage_weights(
        self, total_tokens: int, windows: List[WindowSpec]
    ) -> List[float]:
        """Compute coverage weights w_j for each window according to Section 9 formula."""
        if not windows or total_tokens <= 0:
            return []

        # Count how many windows cover each token: c_i
        token_coverage = [0] * total_tokens
        for w in windows:
            for t in w.token_indices:
                if 0 <= t < total_tokens:
                    token_coverage[t] += 1

        # w_j = sum_{i in window j} (1 / c_i)
        weights: List[float] = []
        for w in windows:
            w_sum = sum(
                (1.0 / token_coverage[t])
                for t in w.token_indices
                if 0 <= t < total_tokens and token_coverage[t] > 0
            )
            weights.append(w_sum)

        return weights

    def aggregate_logits(
        self,
        window_logits: List[float],
        weights: List[float],
    ) -> float:
        """Aggregate window logits into a single document logit z_document."""
        if not window_logits or not weights:
            return 0.0

        if len(window_logits) != len(weights):
            raise ValueError("Window logits and weights list must have identical length")

        total_weight = sum(weights)
        if total_weight <= 0:
            return sum(window_logits) / len(window_logits)

        weighted_sum = sum(w * z for w, z in zip(weights, window_logits))
        return weighted_sum / total_weight
