# Model Manifest and Provenance Registry

**Specification Date:** 19 October 2026  
**Status:** Frozen Initial Configuration (Phase 0)  
**Rule:** No arbitrary models or weights are loaded without explicit manifest records, checksum verification, and audited loaders.

---

## 1. Rephrasing Models

### 1.1 Baseline Profile: `qwen-9b-q6k`
- **Model Name:** Qwen 3.5 9B (Quantized Q6_K)
- **Base Architecture:** Qwen2/Qwen3 transformer architecture (Dense autoregressive decoder)
- **Upstream Repository:** `Qwen/Qwen3.5-9B` (Apache 2.0)
- **Quantization Repository:** `bartowski/Qwen_Qwen3.5-9B-GGUF`
- **Artifact File:** `Qwen3.5-9B-Q6_K.gguf`
- **Expected Size:** ~7.96 GB
- **Runtime Backend:** Native `llama.cpp` (`llama-server`)
- **Execution Target:** CPU (AVX2 / AVX-VNNI), multi-threaded (`-t 16` or optimal measured thread count), optional Vulkan acceleration tested separately.
- **Context Configuration:**
  - Context Window ($N_{ctx}$): 4,096 tokens (planning baseline; scalable to 8,192 only if memory admission allows).
  - Batch size ($N_{batch}$): 512 tokens.
  - Flash Attention: enabled where supported by the binary.
- **Chat Template & Thinking Mode:**
  - Standard ChatML / Qwen chat template.
  - Non-thinking mode configured explicitly (avoiding internal `<think>` reasoning traces in output).
- **Validation Status:** Candidate Baseline (Pending full locked benchmark in Phase 6).

### 1.2 Rejected / High-Capacity Profile: `qwen-27b-q4km`
- **Model Name:** Qwen 3.6 27B (Quantized Q4_K_M)
- **Upstream Repository:** `Qwen/Qwen3.6-27B` (Apache 2.0)
- **Quantization Repository:** `ggml-org/Qwen3.6-27B-GGUF`
- **Artifact File:** `Qwen3.6-27B-Q4_K_M.gguf` (~19.1 GB)
- **Feasibility Status:** **REFUSED** on this host (violates NFR-06 6.0 GiB OS headroom requirement on 32 GB system with ~17 GiB available).

---

## 2. Detection Models

### 2.1 English Baseline: `desklib-v1.01-en`
- **Model Name:** Desklib AI Text Detector v1.01
- **Upstream Repository:** `desklib/ai-text-detector-v1.01`
- **Base Architecture:** `microsoft/deberta-v3-large`
- **Classification Head:** Custom masked mean pooling layer + 1-logit linear layer (`1024 -> 1`).
- **Audit Requirement:**
  - **Do NOT** load using naive `AutoModelForSequenceClassification` with default classifier weights (which would randomly initialize a new head).
  - Loader must explicitly map weights:
    - Base: DeBERTa encoder (`deberta` or `model` prefix).
    - Head: `classifier.weight` and `classifier.bias` (or equivalent audited state dict keys).
  - Verification: Loader test must assert zero uninitialized keys and verify known boundary fixtures (AT-12, AT-20).
- **Format:** Hugging Face safetensors (`model.safetensors`).
- **Precision:** Float32 on CPU (`torch.float32`, `torch.inference_mode()`, `eval()`).
- **Windowing Parameters:**
  - Maximum window tokens: 512 tokens.
  - Window stride / overlap: 448 tokens stride (64 tokens overlap).
  - Aggregation rule: Token-coverage weighted logit average across overlapping windows.
- **Validation Status:** Candidate English Baseline (Subject to FPR $\le 1\%$ and Recall $\ge 80\%$ acceptance gate).

### 2.2 Experimental Multilingual: `oculus-v2.0-multi`
- **Model Name:** Oculus Multilingual v2.0
- **Upstream Repository:** `danibor/oculus-v2.0-multilingual`
- **Base Architecture:** `xlm-roberta-large`
- **Classification Head:** Masked mean pooling + linear head.
- **Intended Language Scope:** German (experimental) & Multilingual comparison.
- **Status:** **EXPERIMENTAL** (DET-10). Must be visibly labeled as experimental in the GUI until independent German evaluation satisfies acceptance criteria.

---

## 3. Score Semantics & Decision Thresholds

### 3.1 Detector Output Labels
In accordance with DET-02 and DET-04:
- `Strong AI signal`: Logit score above calibrated high threshold $\tau_{\text{high}}$.
- `Low AI signal`: Logit score below calibrated low threshold $\tau_{\text{low}}$.
- `Uncertain`: Logit score falls strictly between $\tau_{\text{low}}$ and $\tau_{\text{high}}$.
- `Insufficient text`: Input contains $< 150$ eligible prose words (DET-03).
- `Unsupported language/content`: Language not validated or input lacks valid prose (DET-08).
- `Error`: Backend, model, or hardware failure.

### 3.2 Display Guardrails
- Scores are displayed on a 0–100 calibrated model scale only when a valid calibration profile exists.
- The UI explicitly clarifies: "Model score indicates detection signal strength within validated distribution, NOT percentage of AI-generated words or proof of human authorship."
