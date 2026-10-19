"""Audited model loader and classification adapter for AI text detectors.

Loads safetensors directly, audits missing/unexpected keys, verifies the custom
masked mean pooling head, and refuses to run with randomly initialized weights.
Always sets trust_remote_code=False.
"""

from __future__ import annotations

import math
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
    expected_encoder_prefix="model.",
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



class LocalDesklibDetector:
    """CPU adapter for the upstream mean-pooling + linear-head architecture.

    Only local safetensors/config/tokenizer files are accepted. Strict state loading
    rejects missing, extra and mismatched tensors instead of inventing a head.
    """

    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir).expanduser()
        weights_path = self.model_dir / "model.safetensors"
        if not weights_path.is_file() or not (self.model_dir / "config.json").is_file():
            raise ModelLoadError(
                f"Detector files missing in {self.model_dir}. Run scripts/download_models.sh "
                "to obtain weights, config and tokenizer together."
            )
        try:
            import torch
            from safetensors.torch import load_file
            from transformers import AutoConfig, AutoModel, AutoTokenizer
        except ImportError as exc:
            raise ModelLoadError("Detector dependencies missing. Run scripts/setup_env.sh --detector.") from exc

        from localtext.inference.memory_guard import MemoryGuard
        MemoryGuard().enforce_admission("desklib-v1.01-en", custom_footprint_bytes=6 * 1024**3)
        try:
            AuditedDetectorLoader().load_and_verify_weights(weights_path)
            config = AutoConfig.from_pretrained(str(self.model_dir), local_files_only=True,
                                                trust_remote_code=False)
            if config.model_type != "deberta-v2":
                raise ModelLoadError("Expected the Desklib DeBERTa-v3 detector architecture.")
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_dir), local_files_only=True, trust_remote_code=False, use_fast=True
            )
            if not self.tokenizer.is_fast:
                raise ModelLoadError("A fast tokenizer is required to map scores back to source text.")
            # The attribute names intentionally match the upstream checkpoint keys.
            class MeanPoolClassifier(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.model = AutoModel.from_config(config, trust_remote_code=False)
                    self.classifier = torch.nn.Linear(config.hidden_size, 1)

                def forward(self, input_ids, attention_mask):
                    hidden = self.model(input_ids=input_ids, attention_mask=attention_mask)[0]
                    mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
                    pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                    return self.classifier(pooled)

            self.model = MeanPoolClassifier()
            self.model.load_state_dict(load_file(str(weights_path), device="cpu"), strict=True)
            self.model.eval()
            self.torch = torch
            self.window_tokens = min(512, config.max_position_embeddings) - self.tokenizer.num_special_tokens_to_add()
            if self.window_tokens <= 64:
                raise ModelLoadError("Unsupported detector context size.")
        except ModelLoadError:
            raise
        except Exception as exc:
            raise ModelLoadError(f"Cannot load the local detector: {exc}") from exc

    def tokenize(self, text):
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                                 truncation=False)
        return encoded["input_ids"], encoded["offset_mapping"]

    def score_tokens(self, token_ids):
        ids = self.tokenizer.build_inputs_with_special_tokens(token_ids)
        input_ids = self.torch.tensor([ids], dtype=self.torch.long)
        with self.torch.inference_mode():
            value = self.model(input_ids, self.torch.ones_like(input_ids)).item()
        if not math.isfinite(value):
            raise ModelLoadError("Detector produced a non-finite score.")
        return float(value)
