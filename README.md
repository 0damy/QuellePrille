# LocalText / QuellePrille

A local Qt desktop app for reviewing model-generated rewrites and inspecting an English AI-text detector's output. Runtime inference uses **local Ollama** for rephrasing and **local Desklib weights on CPU** for detection. Docker is unnecessary for this native desktop path.

This repair replaces the original GUI/CLI word-substitution demos and the detector's constant zero logits. It does **not** establish QuillBot-equivalent quality or validated detection accuracy. A low score does not prove human authorship. The detector has no local calibration dataset, so the GUI labels its sigmoid output **raw, uncalibrated model signal**, not a percentage of AI-written text.

## Install and open on Arch

From the repository directory:

```bash
bash scripts/setup_env.sh
bash scripts/run_app.sh
```

Setup creates `.venv` with access to system packages and installs the app plus Qt dependencies. If Qt is already installed with pacman, that installation can be reused. If your current Arch Python has no compatible wheel for a dependency, use an installed Python 3.12 or 3.13 to create a **new** environment; an existing `.venv` keeps its original interpreter. Do not mix Python versions inside one environment.

The repairs were exercised on Python 3.12 with offscreen Qt. Arch/Wayland and Python 3.14 still require verification on your machine.

## Rephrasing

1. Install Ollama using its [Linux instructions](https://docs.ollama.com/linux), then start a local server. For a manually started server:

   ```bash
   OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
   ```

   If Ollama is already running as a service, configure these environment variables on that service rather than starting a second server. Cloud features should be disabled on the daemon too.

2. In another terminal, list downloaded models:

   ```bash
   ollama list
   ```

   If none is installed, an explicit online setup option is `ollama pull qwen3:8b`. This matches the GUI's default model name; it is a starting configuration, **not a quality benchmark or a claim that it is the best model for your hardware**. A different downloaded instruction model can be selected.

3. In GUI **Settings**, enter the exact installed model name. The app never silently substitutes another model. Cloud-backed models are refused before sending source text. No text is sent to Hugging Face.
4. Paste text in **Rephrase**, choose language/mode/strength, optionally freeze terms, and click **Rephrase**. The Custom mode has its own instruction field.
5. Review the diff. **Accept Changes** replaces matching source spans; **Reject** discards the proposal. An edited, cancelled, truncated or incomplete result cannot replace the document. If preservation checks fail twice, that block keeps its source text and the status reports a partial result.

Ollama's chat template handles the system and user messages. Thinking is disabled when the server reports that capability. Requests stream even without a live text preview, so cancellation is checked between response chunks. The app keeps one worker alive until it actually stops. During model loading or a stalled response, cancellation may wait for the current operation/read timeout (up to 120 seconds); closing the window requests cancellation and waits without destroying the running thread.

The app sets an 8,192-token maximum context, reserves output/template space, and rejects prompts exceeding a conservative UTF-8 byte budget. Oversized passages may need splitting. Ollama unloads the selected model after each request to limit retained RAM; this can make multi-chunk rewrites slower.

The older llama.cpp client/process modules remain in the repository, but this repaired GUI and CLI use Ollama only. They do not auto-launch or auto-select a llama.cpp server.

## Detection

Install detector dependencies, then explicitly download its files:

```bash
bash scripts/setup_env.sh --detector
bash scripts/download_models.sh
```

The installer requests CPU PyTorch if PyTorch is absent, avoiding an unnecessary NVIDIA stack on an Intel machine. The download is approximately 1.8 GB. It resolves the upstream reference to one commit and records that commit and SHA-256 hashes in `localtext-manifest.json`. To reproduce a particular snapshot, supply `--revision COMMIT_SHA` to `download_models.sh`.

Default destination: `${XDG_DATA_HOME:-$HOME/.local/share}/localtext/models/desklib`. Select that folder in GUI **Settings**. The old `desklib_model.safetensors` file alone is insufficient: the matching config and tokenizer are also needed.

Paste at least 150 words of English prose into **Detect**. The detector:

- Loads local safetensors strictly into the upstream encoder + masked-mean-pooling + linear-head architecture. Missing or incompatible tensors are errors.
- Uses the actual tokenizer and overlapping windows, including the end of long input; excluded code/table/blockquote regions are not scored.
- Runs on a worker thread, checks cancellation between windows, and discards results if the input or language changed.
- Shows an uncalibrated document signal. English is the only supported detector language in this implementation. German detection is explicitly unsupported.

Runtime `from_pretrained` calls use `local_files_only=True` and `trust_remote_code=False`. No detector files are downloaded by clicking Analyze. Loading checks an estimated 6 GiB peak allocation plus a 6 GiB OS reserve; this is a conservative admission estimate, not a memory guarantee. Detection currently reloads and releases the model for each job.

## Verification and remaining limits

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

The regression suite checks real local HTTP chat streaming with a test server, refusal of missing/cloud models, truncation and cancellation, GUI thread lifetime, stale/rejected output, source-span assembly, and strict tensor loading with a tiny synthetic DeBERTa checkpoint. Qt/tensor tests skip if their optional dependencies are absent. Synthetic tests verify implementation behavior; they do not measure production detection accuracy or rewrite quality.

Before using it for substantive work on your machine:

1. Start the GUI and confirm the selected local model appears in `ollama list`.
2. Rewrite a short paragraph with a number, a citation and a negation. Check meaning manually and accept/reject the result.
3. Cancel a longer job, then edit source during another job. Confirm neither result replaces your edited text.
4. Run detection on two known-origin English samples and a document longer than one window. Confirm the model loads and the raw signals/windows are real. This is only a smoke check, not an accuracy evaluation.
5. Repeat after disabling external network access, while retaining loopback for Ollama.

Preservation checks are heuristics, not proof of semantic equivalence. The full production detector checkpoint, a real Ollama model, Arch/Wayland performance, and quality across your writing domains still need testing. The original specification and historical worklog contain aspirational requirements and earlier completion claims; this README describes the repaired implementation's actual scope. DOCX/PDF import, calibrated thresholds, a German detector, and per-block GUI acceptance are not implemented here.

## Upstream references

- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Ollama local-only mode](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features)
- [Desklib model card and reference architecture (MIT)](https://huggingface.co/desklib/ai-text-detector-v1.01)
