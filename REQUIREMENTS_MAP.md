# LocalText Requirement-to-Test Mapping

**Document Version:** 1.0  
**Date:** 19 October 2026  
**Coverage:** All MUST/SHOULD requirements and Acceptance Test scenarios from the LocalText Specification.

---

## 1. Application Requirements (APP-01 to APP-09)

| ID | Requirement Summary | Implementation Component | Test / Verification Method |
|---|---|---|---|
| **APP-01** | Desktop entry, no terminal needed for normal use; Detect, Rephrase, Settings views | `src/localtext/gui/main_window.py`, `scripts/install_desktop.sh` | Manual GUI launch, integration test for tab switching |
| **APP-02** | Typing/pasting, TXT/MD import, word count, active language, export to new file | `src/localtext/gui/editor_widget.py`, `src/localtext/storage/document_io.py` | `tests/test_document_io.py` (import/export UTF-8 TXT/MD, atomic write) |
| **APP-03** | Explicit EN/DE selection; no silent detector fallback on uncertainty | `src/localtext/gui/language_selector.py`, controller state | `tests/test_language_routing.py` |
| **APP-04** | Responsive GUI during inference, progress stages, active Cancel control | `src/localtext/inference/job_controller.py`, `QThread` workers | `tests/test_cancellation.py`, measured UI responsiveness |
| **APP-05** | Verbatim original preservation, undo history, revision tagging, stale results indicator | `src/localtext/storage/document_state.py` | `tests/test_document_state.py` (revision bumps, stale flag check) |
| **APP-06** | Actionable errors for missing models, OOM, incompatible weights; never plausible fakes | `src/localtext/inference/error_handler.py` | `tests/test_error_handling.py` (simulated OOM, bad weights, missing files) |
| **APP-07** | No saved document history by default; explicit session save/clear | `src/localtext/storage/session_manager.py` | `tests/test_session_privacy.py` (verify clean startup, atomic export) |
| **APP-08** | Keyboard navigation, readable scaling, light/dark theme support, non-color status indicators | `src/localtext/gui/theme.py`, Qt style sheets | Manual inspection and keyboard navigation walkthrough |
| **APP-09** | 10,000 displayed words and 1 MiB UTF-8 input limit; clear limit message | `src/localtext/rephrase/chunker.py`, UI validator | `tests/test_input_limits.py` |

---

## 2. Detection Requirements (DET-01 to DET-11)

| ID | Requirement Summary | Implementation Component | Test / Verification Method |
|---|---|---|---|
| **DET-01** | Trained detection model with audited loader; no LLM guessing | `src/localtext/detection/model_loader.py` | `tests/test_detector_loader.py` (assert audited head keys, no random init) |
| **DET-02** | Strong AI, Low AI, Uncertain, Insufficient text, Unsupported, Error | `src/localtext/detection/pipeline.py` | `tests/test_detector_labels.py` (boundary fixture evaluation) |
| **DET-03** | 150 prose words minimum for scoring; otherwise return Insufficient text | `src/localtext/detection/preprocessor.py` | `tests/test_detector_preprocessor.py` (<150 words returns Insufficient) |
| **DET-04** | 0–100 model score only for supported text; labeled model score; hidden if uncalibrated | `src/localtext/detection/calibrator.py` | `tests/test_calibrator.py` |
| **DET-05** | Analyze all eligible prose without silent truncation; report coverage | `src/localtext/detection/windowing.py` | `tests/test_windowing.py` (large text token coverage accounting) |
| **DET-06** | Highlight scored passage windows, show character ranges and tooltips | `src/localtext/gui/highlighter.py` | `tests/test_highlighter_offsets.py` (Unicode / UTF-16 offset integrity) |
| **DET-07** | Show model identity, validation status, scope, evaluation date, uncertainty info | `src/localtext/gui/detector_view.py` | GUI inspection & manifest metadata test |
| **DET-08** | Explicit handling of mixed-language, code, tables, quotes; abstain if prose cannot be isolated | `src/localtext/detection/preprocessor.py` | `tests/test_detector_preprocessor.py` (code & table exclusion) |
| **DET-09** | Export local JSON/Markdown report with score semantics, ranges, coverage, manifest | `src/localtext/detection/report_exporter.py` | `tests/test_report_exporter.py` |
| **DET-10** | Unvalidated profiles must be marked Experimental; no authoritative appearance | `src/localtext/models/manifest.py` | `tests/test_manifest_status.py` |
| **DET-11** | Sentence-level localization only when validated; no fabricated 4-way labels | `src/localtext/detection/pipeline.py` | Code audit & test ensuring binary logit windowing only |

---

## 3. Rephrasing Requirements (REP-01 to REP-13)

| ID | Requirement Summary | Implementation Component | Test / Verification Method |
|---|---|---|---|
| **REP-01** | 10 defined modes (Standard, Fluency, Formal, Academic, Simple, Natural, Creative, Shorten, Expand, Custom) | `prompts/modes/` & `src/localtext/rephrase/prompts.py` | `tests/test_prompts.py` (all 10 modes exist and follow prompt contract) |
| **REP-02** | Low, Medium, High change strength without weakening meaning preservation | `src/localtext/rephrase/prompts.py` | Prompt generation test for strength constraints |
| **REP-03** | Side-by-side source/output, word-level diff, counts, copy/export controls | `src/localtext/gui/rephrase_view.py`, `src/localtext/rephrase/diff.py` | `tests/test_diff.py` (character/word-level diff correctness) |
| **REP-04** | Whole-text and selected-passage rewriting; read-only context not rewritten or duplicated | `src/localtext/rephrase/pipeline.py` | `tests/test_rephrase_pipeline.py` (target vs context isolation) |
| **REP-05** | Freeze exact words/phrases; preserve all occurrences and capitalization | `src/localtext/rephrase/protection.py` | `tests/test_protection.py` (exact preservation of user-frozen words) |
| **REP-06** | Auto-protect citations, URLs, emails, code spans, equations, numbers, dates, units | `src/localtext/rephrase/protection.py` | `tests/test_protection.py` (regex + boundary detection for citations/math) |
| **REP-07** | Meaning, negation, modality, facts, scope retained; no invented claims | `src/localtext/rephrase/preservation_checker.py` | `tests/test_preservation_checker.py` (checks negation, entities, numbers) |
| **REP-08** | Primary candidate + up to 2 alternatives; no ranking by detector score | `src/localtext/inference/llama_client.py` | `tests/test_alternatives.py` |
| **REP-09** | Accept/reject individual blocks with undo; retain block identities | `src/localtext/storage/document_state.py` | `tests/test_block_operations.py` (block accept/reject/undo) |
| **REP-10** | Deterministic preservation checks; 1 bounded repair attempt; keep original on conflict | `src/localtext/rephrase/pipeline.py` | `tests/test_repair_policy.py` (fail -> repair -> fallback to original) |
| **REP-11** | Long-document chunking and token budgeting; preserve block order | `src/localtext/rephrase/chunker.py` | `tests/test_chunker.py` (split paragraphs, reassemble without drops) |
| **REP-12** | Contextual word/phrase alternatives with surrounding sentence (SHOULD) | `src/localtext/rephrase/alternatives.py` | Unit test for alternative suggestion |
| **REP-13** | Save reusable custom style instructions locally without overriding preservation (SHOULD) | `src/localtext/storage/custom_styles.py` | `tests/test_custom_styles.py` |

---

## 4. Nonfunctional Requirements (NFR-01 to NFR-10)

| ID | Requirement Summary | Implementation Component | Test / Verification Method |
|---|---|---|---|
| **NFR-01** | Zero external network calls in normal offline operation after setup | `src/localtext/inference/`, socket check | `tests/test_offline_egress.py` (blocked network test) |
| **NFR-02** | XDG directories for data/config/models; secrets in private runtime dir; text in RAM | `src/localtext/config.py` | `tests/test_xdg_paths.py` (verify directory layout and permissions) |
| **NFR-03** | Inference listeners on loopback only; authenticated with fresh random local secret | `src/localtext/inference/llama_process.py` | `tests/test_security_loopback.py` (verify 127.0.0.1 and token auth) |
| **NFR-04** | Pinned dependencies, runtime revisions, model hashes, prompts, calibration | `pyproject.toml`, `MODELS.md` | Manifest verification test |
| **NFR-05** | CPU support mandatory; Vulkan acceleration optional; hardware tested first | `src/localtext/inference/runtime_selector.py` | CPU run test and Vulkan detection test |
| **NFR-06** | Memory admission check before loading model; $\ge 6$ GiB OS headroom | `src/localtext/inference/memory_guard.py` | `tests/test_memory_guard.py` (admission pass for 9B, refuse for 27B) |
| **NFR-07** | GUI responsiveness $<100$ ms; Cancel acknowledged $<250$ ms; release $<5$ s | `src/localtext/inference/job_controller.py` | `tests/test_cancellation_timing.py` |
| **NFR-08** | No silent fallback or degradation of model/quantization/language on failure | `src/localtext/inference/error_handler.py` | `tests/test_error_handling.py` |
| **NFR-09** | Default logs must not contain private text, prompts, outputs, or secrets | `src/localtext/utils/logging.py` | `tests/test_log_privacy.py` (search logs for unique canary strings) |
| **NFR-10** | Crash/error data preservation; atomic file saves with confirmation on overwrite | `src/localtext/storage/document_io.py` | `tests/test_atomic_save.py` (atomic rename and overwrite check) |

---

## 5. Acceptance Test Scenarios (AT-01 to AT-20)

| ID | Scenario | Automated Test File |
|---|---|---|
| **AT-01** | Offline launch after setup with network blocked | `tests/acceptance/test_at01_offline_launch.py` |
| **AT-02** | Unauthenticated request to local inference listener rejected | `tests/acceptance/test_at02_unauthenticated_request.py` |
| **AT-03** | Empty, whitespace, or $<150$ word input produces Insufficient Text | `tests/acceptance/test_at03_insufficient_text.py` |
| **AT-04** | German text when only English detector installed produces Unsupported | `tests/acceptance/test_at04_unsupported_language.py` |
| **AT-05** | 10,000-word document covered completely without silent truncation | `tests/acceptance/test_at05_long_document_coverage.py` |
| **AT-06** | Protected terms (`HZD`, `3.5%`, `48 km`, `[12]`, `\cite{...}`, email, code) preserved | `tests/acceptance/test_at06_protected_spans.py` |
| **AT-07** | Modality and negation ("may reduce errors but does not prove causality") retained | `tests/acceptance/test_at07_modality_negation.py` |
| **AT-08** | Entity-quantity attachment ("Alice received 5, Bob received 9") retained | `tests/acceptance/test_at08_entity_attachment.py` |
| **AT-09** | Prompt injection attack ("Ignore previous instructions...") treated purely as data | `tests/acceptance/test_at09_prompt_injection.py` |
| **AT-10** | Cancel during loading/inference releases worker cleanly within 5s | `tests/acceptance/test_at10_cancel_worker.py` |
| **AT-11** | Source edited while job runs: previous result cannot overwrite new text | `tests/acceptance/test_at11_stale_result_invalidation.py` |
| **AT-12** | Corrupt/missing weights or classifier head mismatch fails safely with error | `tests/acceptance/test_at12_corrupt_weights_handling.py` |
| **AT-13** | 27B model refused gracefully by memory admission check | `tests/acceptance/test_at13_memory_refusal.py` |
| **AT-14** | Rephrasing token limit / lost chunk results in partial/failed status, preserving original | `tests/acceptance/test_at14_chunk_failure_fallback.py` |
| **AT-15** | Emoji, umlauts, ß, combining characters, UTF-16/Unicode offset integrity | `tests/acceptance/test_at15_unicode_offsets.py` |
| **AT-16** | Freeze repeated or overlapping terms without replacement collisions | `tests/acceptance/test_at16_freeze_occurrences.py` |
| **AT-17** | Private canary strings do not appear in any application/backend logs | `tests/acceptance/test_at17_log_canary_leakage.py` |
| **AT-18** | Restart after explicit session save restores only explicitly saved data | `tests/acceptance/test_at18_session_restore.py` |
| **AT-19** | Model update or calibration removal invalidates previous validation badge | `tests/acceptance/test_at19_validation_invalidation.py` |
| **AT-20** | Synthetic boundary fixtures for classifier verify label direction and thresholds | `tests/acceptance/test_at20_classifier_boundary.py` |
