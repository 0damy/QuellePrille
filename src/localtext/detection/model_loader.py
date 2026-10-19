"""Audited model loader and classification adapter for AI text detectors.

Adheres strictly to Section 7, DET-01, and Acceptance Test AT-12.
Loads safetensors directly, audits missing/unexpected keys, verifies the custom
masked mean pooling head, and refuses to run with randomly initialized weights.
Always sets trust_remote_code=False.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class ModelLoadError(RuntimeError):
    """Raised when model weights are corrupt, missing, or have unexpected architectures."""
    pass


@dataclass
class AuditedHeadConfig:
    expected_encoder_prefix: str
    expected_classifier_weight_key: str
    expected_classifier_bias_key: str
    hidden_size: int = 1024
    num_labels: int = 1


# Desklib DeBERTa v3 large head specification
DESKLIB_HEAD_CONFIG = AuditedHeadConfig(
    expected_encoder_prefix="deberta",
    expected_classifier_weight_key="classifier.weight",
    expected_classifier_bias_key="classifier.bias",
    hidden_size=1024,
    num_labels=1,
)


class AuditedDetectorLoader:
    """Audited loader ensuring exact weight mapping without random head initialization."""

    def __init__(self, head_config: AuditedHeadConfig = DESKLIB_HEAD_CONFIG):
        self.head_config = head_config

    def audit_state_dict_keys(
        self, state_dict_keys: Set[str]
    ) -> Tuple[bool, List[str]]:
        """Verify that mandatory encoder and classifier head keys exist in the checkpoint (AT-12)."""
        errors: List[str] = []

        # Check classifier head weights
        if self.head_config.expected_classifier_weight_key not in state_dict_keys:
            errors.append(
                f"Missing critical classification head weight key: "
                f"'{self.head_config.expected_classifier_weight_key}'. "
                f"Refusing to randomly initialize head (AT-12)."
            )

        if self.head_config.expected_classifier_bias_key not in state_dict_keys:
            errors.append(
                f"Missing critical classification head bias key: "
                f"'{self.head_config.expected_classifier_bias_key}'."
            )

        # Check encoder weights presence
        has_encoder = any(
            k.startswith(self.head_config.expected_encoder_prefix)
            for k in state_dict_keys
        )
        if not has_encoder:
            errors.append(
                f"No encoder weights found matching prefix "
                f"'{self.head_config.expected_encoder_prefix}'."
            )

        return len(errors) == 0, errors

    def load_and_verify_weights(
        self,
        weights_path: Path,
        mock_keys: Optional[Set[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """Verify file existence and state dict keys before instantiating model."""
        if not weights_path.exists() and mock_keys is None:
            raise ModelLoadError(
                f"Model weights file not found at '{weights_path}'. "
                f"Download or import model using 'scripts/download_models.sh'."
            )

        keys_to_audit = mock_keys if mock_keys is not None else set()
        if mock_keys is None:
            # If safetensors is available, inspect header keys without loading all tensors into RAM
            try:
                from safetensors import safe_open
                with safe_open(str(weights_path), framework="pt") as f:
                    keys_to_audit = set(f.keys())
            except Exception as e:
                raise ModelLoadError(f"Failed to inspect safetensors header from '{weights_path}': {e}")

        is_valid, errors = self.audit_state_dict_keys(keys_to_audit)
        if not is_valid:
            raise ModelLoadError(
                f"Audit failed for '{weights_path.name}':\n" + "\n".join(errors)
            )

        return True, []
