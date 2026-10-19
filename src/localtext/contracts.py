"""LocalText core typed data contracts and state records.

Adheres strictly to Section 10 of the LocalText specification.
All internal text offsets are zero-based, half-open Unicode code-point ranges [start, end)
indexing into the verbatim, unchanged source string.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class JobState(str, enum.Enum):
    QUEUED = "queued"
    LOADING = "loading"
    RUNNING = "running"
    CHECKING = "checking"
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DetectorLabel(str, enum.Enum):
    STRONG_AI = "Strong AI signal"
    LOW_AI = "Low AI signal"
    UNCERTAIN = "Uncertain"
    INSUFFICIENT_TEXT = "Insufficient text"
    UNSUPPORTED_CONTENT = "Unsupported language/content"
    ERROR = "Error"


class ValidationStatus(str, enum.Enum):
    VALIDATED = "validated"
    EXPERIMENTAL = "experimental"
    UNVALIDATED = "unvalidated"
    DEPRECATED = "deprecated"


class ChangeStrength(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RephraseMode(str, enum.Enum):
    STANDARD = "standard"
    FLUENCY = "fluency"
    FORMAL = "formal"
    ACADEMIC = "academic"
    SIMPLE = "simple"
    NATURAL = "natural"
    CREATIVE = "creative"
    SHORTEN = "shorten"
    EXPAND = "expand"
    CUSTOM = "custom"


@dataclass(frozen=True)
class TextSpan:
    """Zero-based half-open Unicode code-point range [start, end)."""
    start: int
    end: int
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.start < 0:
            raise ValueError(f"Span start cannot be negative: {self.start}")
        if self.end < self.start:
            raise ValueError(f"Span end ({self.end}) cannot be less than start ({self.start})")

    @property
    def length(self) -> int:
        return self.end - self.start

    def slice_from(self, text: str) -> str:
        return text[self.start : self.end]

    def overlaps(self, other: TextSpan) -> bool:
        return max(self.start, other.start) < min(self.end, other.end)


@dataclass(frozen=True)
class ProtectedSpan:
    """Exact span of text protected from modification."""
    span: TextSpan
    original_text: str
    reason: str  # e.g., 'frozen_word', 'citation', 'number', 'code', 'url', 'email'
    placeholder: Optional[str] = None


@dataclass(frozen=True)
class DocumentSnapshot:
    """Immutable snapshot of document state at a specific revision."""
    document_id: str
    revision: int
    original_text: str
    language: str  # 'en', 'de', or 'auto'
    selected_source_ranges: Tuple[TextSpan, ...] = ()
    word_count: int = 0

    def __post_init__(self):
        if self.revision < 0:
            raise ValueError("Revision must be non-negative")
        if not self.word_count and self.original_text:
            # Simple whitespace word count for snapshot baseline
            object.__setattr__(self, "word_count", len(self.original_text.split()))


@dataclass(frozen=True)
class TargetBlock:
    """A target prose chunk to be processed by rephrasing."""
    block_id: int
    source_span: TextSpan
    source_text: str
    context_prefix: str = ""
    context_suffix: str = ""
    protected_spans: Tuple[ProtectedSpan, ...] = ()


@dataclass(frozen=True)
class RewriteRequest:
    """Contract for a rephrase execution job."""
    job_id: str
    snapshot_revision: int
    model_profile_id: str
    mode: RephraseMode
    strength: ChangeStrength
    custom_style: str = ""
    protected_spans: Tuple[ProtectedSpan, ...] = ()
    target_blocks: Tuple[TargetBlock, ...] = ()


@dataclass
class CandidateBlock:
    """A candidate rewrite for a specific target block."""
    block_id: int
    candidate_id: int
    rewritten_text: str
    diff_html: str = ""
    is_repaired: bool = False
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RewriteResult:
    """Result of a rephrasing job."""
    job_id: str
    snapshot_revision: int
    status: JobState
    candidate_blocks: List[CandidateBlock] = field(default_factory=list)
    source_to_output_mapping: Dict[int, int] = field(default_factory=dict)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    runtime_version: str = ""
    model_version: str = ""
    prompt_version: str = ""
    timings_ms: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PassageScore:
    """Scored window of text from the detector."""
    window_id: int
    span: TextSpan
    raw_logit: float
    calibrated_score: Optional[float]
    token_count: int


@dataclass
class DetectionResult:
    """Result of a text detection job."""
    job_id: str
    snapshot_revision: int
    status: JobState
    label: DetectorLabel
    score: Optional[float]  # 0.0 to 100.0, or None if Insufficient/Unsupported/Uncalibrated
    score_semantics: str
    language: str
    eligible_ranges: List[TextSpan] = field(default_factory=list)
    excluded_ranges: List[TextSpan] = field(default_factory=list)
    window_results: List[PassageScore] = field(default_factory=list)
    model_id: str = ""
    calibration_id: str = ""
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    timings_ms: Dict[str, float] = field(default_factory=dict)
    analyzed_coverage_ratio: float = 0.0


@dataclass(frozen=True)
class ValidationProfile:
    """Immutable validation record and thresholds for a detector profile."""
    profile_id: str
    task_scope: str
    language: str
    domain_scope: str
    min_length_words: int
    max_length_words: int
    model_sha256: str
    tokenizer_sha256: str
    preprocessing_version: str
    tau_low: float
    tau_high: float
    calibration_artifact_id: str
    dataset_manifest_hash: str
    metrics: Dict[str, float]
    approval_date: str
    status: ValidationStatus


@dataclass(frozen=True)
class ModelManifest:
    """Immutable provenance and runtime configuration for a local model."""
    model_id: str
    upstream_repo: str
    upstream_commit: str
    conversion_repo: str = ""
    conversion_commit: str = ""
    filename: str = ""
    filesize_bytes: int = 0
    sha256: str = ""
    license: str = ""
    local_path: str = ""
    runtime_backend: str = ""  # 'llama.cpp' or 'transformers_pytorch'
    quantization: str = ""
    effective_context_tokens: int = 4096
    chat_template_hash: str = ""
    supported_languages: Tuple[str, ...] = ("en",)
    calibration_id: str = ""
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
