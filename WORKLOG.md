# LocalText Implementation Worklog

All commands run, real results, file changes, and transition records are documented here in accordance with Section 1 and Section 15 of the LocalText Specification.

---

## Phase 0: Feasibility & Environment Inspection
**Date:** 19 October 2026  
**Status:** COMPLETE

### Actions & Commands Executed
1. **System & Kernel Inspection:**
   - Command: `uname -a && cat /etc/os-release && lscpu && free -h && df -h . && lsblk`
   - Real Results:
     - OS: Arch Linux (rolling, kernel `7.2.11-arch1-1`, x86_64)
     - CPU: Intel Core Ultra 7 155H (16 cores, 22 threads, max 4.8 GHz, AVX2, AVX-VNNI, SHA)
     - RAM: 30 GiB usable, ~17 GiB available, 15.4 GiB `zram0` swap
     - Storage: NVMe SSD (`/dev/nvme0n1p5`), 236 GiB available
2. **Display & GPU Inspection:**
   - Command: `lspci | grep -i -E "vga|3d|display" && vulkaninfo --summary`
   - Real Results:
     - GPU: Intel Meteor Lake-P [Intel Arc Graphics] (rev 08), Mesa 26.2.5
     - Session: Wayland (`wayland-1`, KDE Plasma 6)
     - Vulkan: API 1.4.354 supported via `Intel(R) Arc(tm) Graphics (MTL)`
3. **Toolchain Inspection:**
   - Command: `python3 -V && gcc --version && cmake --version && cargo --version`
   - Real Results: Python 3.14.8, GCC, CMake, Cargo all present.
4. **Feasibility & Memory Policy Determination:**
   - Headroom rule (NFR-06): Minimum 6 GiB reserved for OS.
   - Max safe allocation: 17 GiB available - 6 GiB = ~11 GiB.
   - Baseline Rephrasing: `Qwen/Qwen3.5-9B` GGUF Q6_K (~7.96 GB file, ~10.5 GiB peak) is **FEASIBLE**.
   - High-Capacity Rephrasing: `Qwen/Qwen3.6-27B` GGUF Q4_K_M (~19.1 GB file, ~24 GiB peak) is **REFUSED** on this host due to memory admission check (AT-13).
   - Baseline Detection: `desklib/ai-text-detector-v1.01` (~1.74 GB safetensors, DeBERTa-v3-large) is **FEASIBLE** on CPU float32 (~2.5 GiB peak).
   - Multilingual Detection: `danibor/oculus-v2.0-multilingual` is **FEASIBLE** as an **EXPERIMENTAL** profile (DET-10).

### Deliverables Created
- `HARDWARE.md`: Hardware specifications, memory admission constraints, and feasibility conclusions.
- `MODELS.md`: Upstream model manifests, quantization, audited classifier requirements, and score semantics.
- `REQUIREMENTS_MAP.md`: Traceability mapping for APP, DET, REP, NFR, and AT scenarios.
- `WORKLOG.md`: Implementation log.

---

## Phase 1: Core Data Contracts, Protection, & Pipeline Engines
**Date:** 19 October 2026  
**Status:** COMPLETE (Core Software & Automated Tests)

### Actions & Commands Executed
1. **Repository & Package Initialization:**
   - Git repository initialized.
   - Virtual environment created with `--system-site-packages` (incorporating system-tested numpy 2.5.4, psutil 7.2.2, requests).
   - Created `pyproject.toml` configuring `localtext` package layout.
2. **Prompts & Contracts Implementation:**
   - Created `prompts/system_preservation.txt` following Section 8 prompt contract verbatim.
   - Created all 10 mode prompt files (`prompts/modes/*.txt`) defining goals, constraints, and length targets.
   - Created `src/localtext/contracts.py` with typed dataclasses, job states, text spans, snapshot revisions, and manifests.
3. **Offset & Coordinate Handling:**
   - Implemented `src/localtext/utils/offsets.py` providing bidirectional mapping between Python Unicode code points and Qt UTF-16 code units (AT-15).
   - Verified with astral characters, emojis (🚀, 🎉), combining marks, and German umlauts.
4. **Memory Guard & Admission Policy:**
   - Implemented `src/localtext/inference/memory_guard.py` enforcing NFR-06 (6.0 GiB OS headroom).
   - Verified that `qwen-9b-q6k` is admitted while `qwen-27b-q4km` is rejected on this 32 GB system, offering the 9B baseline (AT-13).
5. **Runtime Authentication & Secret Management:**
   - Implemented `src/localtext/inference/runtime_auth.py` providing mode 0600 secret files for loopback-only communication (NFR-03, AT-02).
6. **Text Protection Engine:**
   - Implemented `src/localtext/rephrase/protection.py` detecting auto-protected citations (`\cite`, `[12]`), units, quantities, URLs, emails, formulas, and user-frozen words (REP-05, REP-06, AT-06).
   - Deterministic overlap resolution ensures longer spans take precedence and collision-resistant placeholders prevent marker corruption (AT-16).
7. **Document Chunker & Token Budgeting:**
   - Implemented `src/localtext/rephrase/chunker.py` handling long documents up to 10,000 words (APP-09, AT-05) and selected passage rewriting with read-only context (REP-04).
8. **Deterministic Preservation Checker:**
   - Implemented `src/localtext/rephrase/preservation_checker.py` checking negation retention, modality/hedging, and entity-quantity associations (REP-07, REP-10, AT-07, AT-08).
9. **Prompt Builder & Injection Isolation:**
   - Implemented `src/localtext/rephrase/prompts.py` wrapping input strictly as data within delimiters (AT-09).
10. **Difference & Export Markup:**
    - Implemented `src/localtext/rephrase/diff.py` generating accessible word-level HTML diffs (REP-03, APP-08).
11. **Detection Engine & Aggregation:**
    - Implemented `src/localtext/detection/preprocessor.py` filtering non-prose content, enforcing 150-word minimum, and routing languages (DET-03, DET-08, AT-03, AT-04).
    - Implemented `src/localtext/detection/aggregation.py` computing token-coverage weighted document logits across overlapping windows without truncation (DET-05).
    - Implemented `src/localtext/detection/calibrator.py` evaluating decision thresholds ($\tau_{\text{low}}$, $\tau_{\text{high}}$) and score semantics (DET-02, DET-04, AT-20).
    - Implemented `src/localtext/detection/model_loader.py` auditing safetensors keys to prevent random head initialization (DET-01, AT-12).
    - Implemented `src/localtext/detection/pipeline.py` executing the complete detection workflow.
12. **Document State, I/O, & Privacy:**
    - Implemented `src/localtext/storage/document_state.py` with undo/redo, block accept/reject, and stale result invalidation (APP-05, REP-09, AT-11).
    - Implemented `src/localtext/storage/document_io.py` with atomic temp-file rename saves and overwrite protection (APP-02, NFR-10).
    - Implemented `src/localtext/storage/session_manager.py` guaranteeing zero implicit persistence (APP-07, AT-18).
    - Implemented `src/localtext/utils/logging.py` guaranteeing zero document text or secret leakage in logs (NFR-09, AT-17).
13. **Automated Test Suite Verification:**
    - Ran: `PYTHONPATH=src .venv/bin/python -m unittest discover tests`
    - Real Result: Ran 36 tests in 0.009s — ALL 36 TESTS PASS.

### Next Steps
- Implement `src/localtext/inference/llama_process.py` and `job_controller.py` for child process management and cancellation (AT-10, APP-04).
- Implement desktop GUI views (`src/localtext/gui/`) with PySide6 / Qt6 widgets.
- Proceed to model asset acquisition and locked evaluation gate.

