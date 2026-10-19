"""Native Qt UI with one background job and explicit local model settings."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from localtext.contracts import (
    ChangeStrength,
    JobState,
    RephraseMode,
    RewriteRequest,
)
from localtext.detection.pipeline import DetectionPipeline
from localtext.config import get_models_dir
from localtext.inference.ollama_client import OllamaHttpClient
from localtext.inference.memory_guard import MemoryGuard
from localtext.rephrase.chunker import DocumentChunker
from localtext.rephrase.diff import TextDiffEngine
from localtext.rephrase.pipeline import RephrasePipeline, assemble_rewrite
from localtext.storage.document_state import DocumentStateManager
from localtext.storage.session_manager import SessionManager


def create_qt_app() -> "MainWindow":
    """Instantiate the Qt Application and MainWindow."""
    from PySide6.QtCore import QThread, Qt, Signal, QSettings
    from PySide6.QtWidgets import (
        QComboBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSplitter,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    class Worker(QThread):
        result_ready = Signal(object)
        error = Signal(str)

        def __init__(self, action):
            super().__init__()
            self.action = action

        def run(self):
            try:
                self.result_ready.emit(self.action())
            except Exception as exc:
                self.error.emit(str(exc))

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("LocalText — Private Detection & Rephrasing")
            self.resize(1100, 750)

            self.doc_state = DocumentStateManager()
            self.session_mgr = SessionManager()
            self.settings = QSettings("LocalText", "LocalText")
            self.diff_engine = TextDiffEngine()

            self._active_worker = None
            self._close_when_finished = False
            self._pending_output = None
            self._rewrite_source = ""
            self._rewrite_blocks = []
            self._cancel_event = threading.Event()

            self._init_ui()

        def _init_ui(self):
            central = QWidget(self)
            self.setCentralWidget(central)
            main_layout = QVBoxLayout(central)

            # Tab workspace: Detect, Rephrase, Settings (APP-01)
            self.tabs = QTabWidget()
            self.rephrase_tab = self._create_rephrase_tab()
            self.detect_tab = self._create_detect_tab()
            self.settings_tab = self._create_settings_tab()

            self.tabs.addTab(self.rephrase_tab, "Rephrase")
            self.tabs.addTab(self.detect_tab, "Detect")
            self.tabs.addTab(self.settings_tab, "Settings")

            main_layout.addWidget(self.tabs)

            # Global progress & status bar (APP-04)
            bottom_bar = QHBoxLayout()
            self.status_lbl = QLabel("Ready")
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 0)  # Indeterminate pulsing animation
            self.progress_bar.setVisible(False)

            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.clicked.connect(self._on_cancel_clicked)

            bottom_bar.addWidget(self.status_lbl, stretch=1)
            bottom_bar.addWidget(self.progress_bar, stretch=0)
            bottom_bar.addWidget(self.cancel_btn, stretch=0)
            main_layout.addLayout(bottom_bar)

        def _create_rephrase_tab(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            # Controls header
            controls = QHBoxLayout()

            # Language selector (APP-03)
            controls.addWidget(QLabel("Language:"))
            self.lang_combo = QComboBox()
            self.lang_combo.addItem("German (de)", "de")
            self.lang_combo.addItem("English (en)", "en")
            controls.addWidget(self.lang_combo)

            # Mode selector (REP-01)
            controls.addWidget(QLabel("Mode:"))
            self.mode_combo = QComboBox()
            for m in RephraseMode:
                self.mode_combo.addItem(m.value.capitalize(), m.value)
            controls.addWidget(self.mode_combo)

            # Strength selector (REP-02)
            controls.addWidget(QLabel("Strength:"))
            self.strength_combo = QComboBox()
            for s in ChangeStrength:
                self.strength_combo.addItem(s.value.capitalize(), s.value)
            self.strength_combo.setCurrentText("Medium")
            controls.addWidget(self.strength_combo)

            # Freeze words (REP-05)
            controls.addWidget(QLabel("Freeze words:"))
            self.freeze_input = QLineEdit()
            self.freeze_input.setPlaceholderText("comma-separated terms")
            controls.addWidget(self.freeze_input)

            self.rephrase_btn = QPushButton("Rephrase")
            self.rephrase_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
            self.rephrase_btn.clicked.connect(self._on_rephrase_clicked)
            controls.addWidget(self.rephrase_btn)

            layout.addLayout(controls)
            self.custom_style = QLineEdit()
            self.custom_style.setPlaceholderText("Instructions for Custom mode")
            layout.addWidget(self.custom_style)

            # Side-by-side editor splitter (REP-03)
            splitter = QSplitter(Qt.Orientation.Horizontal)

            # Source editor
            src_box = QWidget()
            src_layout = QVBoxLayout(src_box)
            src_header = QHBoxLayout()
            src_header.addWidget(QLabel("<b>Source Text</b>"))
            self.src_word_lbl = QLabel("0 words")
            src_header.addStretch(1)
            src_header.addWidget(self.src_word_lbl)
            src_layout.addLayout(src_header)

            self.src_edit = QTextEdit()
            self.src_edit.setPlaceholderText("Type or paste prose here...")
            self.src_edit.textChanged.connect(self._on_src_text_changed)
            src_layout.addWidget(self.src_edit)

            splitter.addWidget(src_box)

            # Rewrite / Output editor
            out_box = QWidget()
            out_layout = QVBoxLayout(out_box)
            out_header = QHBoxLayout()
            out_header.addWidget(QLabel("<b>Rewritten Output (Diff Preview)</b>"))
            self.out_word_lbl = QLabel("0 words")
            out_header.addStretch(1)
            out_header.addWidget(self.out_word_lbl)
            out_layout.addLayout(out_header)

            self.out_edit = QTextEdit()
            self.out_edit.setReadOnly(True)
            out_layout.addWidget(self.out_edit)

            # Accept / Reject buttons (REP-09)
            btn_box = QHBoxLayout()
            self.accept_btn = QPushButton("Accept Changes")
            self.accept_btn.clicked.connect(self._on_accept_clicked)
            self.accept_btn.setEnabled(False)
            self.reject_btn = QPushButton("Reject")
            self.reject_btn.clicked.connect(self._on_reject_clicked)
            btn_box.addWidget(self.accept_btn)
            btn_box.addWidget(self.reject_btn)
            out_layout.addLayout(btn_box)

            splitter.addWidget(out_box)
            splitter.setSizes([500, 500])
            layout.addWidget(splitter)

            return widget

        def _create_detect_tab(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            header = QHBoxLayout()
            header.addWidget(QLabel("<b>Prose Analysis & AI Detector</b>"))

            header.addSpacing(20)
            header.addWidget(QLabel("Language:"))
            self.detect_lang_combo = QComboBox()
            self.detect_lang_combo.addItem("English (en)", "en")
            self.detect_lang_combo.addItem("German (de)", "de")
            header.addWidget(self.detect_lang_combo)

            header.addStretch(1)
            self.detect_btn = QPushButton("Analyze Text")
            self.detect_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
            self.detect_btn.clicked.connect(self._on_detect_clicked)
            header.addWidget(self.detect_btn)
            layout.addLayout(header)

            self.detect_input = QTextEdit()
            self.detect_input.setPlaceholderText("Enter at least 150 words of prose to analyze...")
            layout.addWidget(self.detect_input)

            # Results panel (DET-02, DET-04, DET-07)
            res_box = QWidget()
            res_layout = QVBoxLayout(res_box)
            self.detect_score_lbl = QLabel("<b>Status:</b> Not analyzed")
            self.detect_score_lbl.setStyleSheet("font-size: 14px; padding: 8px;")
            self.detect_details_lbl = QLabel("Desklib: English only. No locally validated accuracy or calibration.")
            self.detect_details_lbl.setWordWrap(True)
            self.detect_details_lbl.setTextFormat(Qt.TextFormat.PlainText)
            res_layout.addWidget(self.detect_score_lbl)
            res_layout.addWidget(self.detect_details_lbl)
            layout.addWidget(res_box)

            return widget

        def _create_settings_tab(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)

            guard = MemoryGuard()
            avail = guard.get_available_memory_bytes() / (1024**3)

            layout.addWidget(QLabel("<h3>System & Privacy Settings</h3>"))
            layout.addWidget(QLabel(f"<b>Available Host Memory:</b> {avail:.2f} GiB"))
            layout.addWidget(QLabel("Ollama model: use the exact local name shown by `ollama list`."))
            self.model_input = QLineEdit(str(self.settings.value(
                "ollama_model", os.environ.get("LOCALTEXT_OLLAMA_MODEL", "qwen3:8b"))))
            layout.addWidget(self.model_input)
            layout.addWidget(QLabel("Detector folder (weights, config and tokenizer):"))
            self.detector_path = QLineEdit(str(self.settings.value(
                "detector_path", str(get_models_dir() / "desklib"))))
            layout.addWidget(self.detector_path)
            privacy = QLabel("Runtime uses local Ollama and local detector files. "
                             "Model downloads are a separate setup step. "
                             "Run Ollama with OLLAMA_NO_CLOUD=1. "
                             "Preservation checks are heuristic: review every rewrite." )
            privacy.setWordWrap(True)
            layout.addWidget(privacy)
            layout.addSpacing(20)
            clear_session_btn = QPushButton("Clear Saved Session & Text Buffers")
            clear_session_btn.clicked.connect(self._on_clear_session_clicked)
            layout.addWidget(clear_session_btn)

            layout.addStretch(1)
            return widget

        def _clear_rewrite(self):
            self._pending_output = None
            self.doc_state.latest_rewrite_result = None
            self.accept_btn.setEnabled(False)
            self.out_edit.clear()
            self.out_word_lbl.setText("0 words")

        def _on_src_text_changed(self):
            text = self.src_edit.toPlainText()
            self.src_word_lbl.setText(f"{len(text.split())} words")
            self.doc_state.set_text(text)
            self._clear_rewrite()

        def _start_job(self, action, on_result, status):
            if self._active_worker is not None:
                return
            self._job_is_detection = on_result == self._on_detection_finished
            self._cancel_event.clear()
            self.rephrase_btn.setEnabled(False)
            self.detect_btn.setEnabled(False)
            self.accept_btn.setEnabled(False)
            self.settings_tab.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.status_lbl.setText(status)
            self._active_worker = Worker(action)
            self._active_worker.result_ready.connect(on_result)
            self._active_worker.error.connect(self._on_job_error)
            self._active_worker.finished.connect(self._on_worker_stopped)
            self._active_worker.start()

        def _on_worker_stopped(self):
            worker = self._active_worker
            self._active_worker = None
            worker.deleteLater()
            self.rephrase_btn.setEnabled(True)
            self.detect_btn.setEnabled(True)
            self.settings_tab.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.accept_btn.setEnabled(self._pending_output is not None and not self.doc_state.is_result_stale)
            if self._close_when_finished:
                self.close()

        def _on_rephrase_clicked(self):
            if self._active_worker is not None:
                return
            text = self.src_edit.toPlainText()
            if not text.strip():
                QMessageBox.warning(self, "Empty Input", "Please enter some text to rephrase.")
                return
            try:
                blocks = DocumentChunker().create_target_blocks(text)
            except ValueError as exc:
                QMessageBox.warning(self, "Input", str(exc))
                return
            model = self.model_input.text().strip()
            if not model:
                QMessageBox.warning(self, "Model", "Enter a local Ollama model name in Settings.")
                return
            self.settings.setValue("ollama_model", model)
            lang = str(self.lang_combo.currentData())
            frozen = [w.strip() for w in self.freeze_input.text().split(",") if w.strip()]
            req = RewriteRequest(
                job_id="gui-rephrase", snapshot_revision=self.doc_state.revision,
                model_profile_id=model, mode=RephraseMode(self.mode_combo.currentData()),
                strength=ChangeStrength(self.strength_combo.currentData()),
                custom_style=self.custom_style.text(), target_blocks=tuple(blocks),
            )
            self._clear_rewrite()
            self._rewrite_source, self._rewrite_blocks = text, blocks
            cancel_event = self._cancel_event

            def action():
                client = OllamaHttpClient(model=model)
                try:
                    return RephrasePipeline().run_rephrase(
                        req, lambda prompt, system: client.generate_completion(
                            prompt, system, cancel_event=cancel_event),
                        cancel_event, language=lang, user_frozen_words=frozen,
                    )
                finally:
                    client.close()

            self._start_job(action, self._on_rephrase_finished, "Rephrasing with local Ollama…")

        def _on_rephrase_finished(self, result):
            if self._cancel_event.is_set() or result.status == JobState.CANCELLED:
                self.status_lbl.setText("Cancelled; output discarded.")
                return
            if not self.doc_state.attach_rewrite_result(result):
                self.status_lbl.setText("Source changed; stale rewrite discarded.")
                return
            try:
                self._pending_output = assemble_rewrite(self._rewrite_source, self._rewrite_blocks, result)
            except ValueError as exc:
                self._clear_rewrite()
                self._on_job_error(str(exc))
                return
            self.out_edit.setHtml(self.diff_engine.render_html_diff(self._rewrite_source, self._pending_output))
            self.out_word_lbl.setText(f"{len(self._pending_output.split())} words")
            if result.failed_checks:
                self.status_lbl.setText("Partial: some blocks kept their original text after failed checks.")
            elif result.warnings:
                self.status_lbl.setText("Rewrite ready with preservation warnings; review before accepting.")
            else:
                self.status_lbl.setText("Rewrite ready for review.")
            self.out_edit.setToolTip("\n".join(result.failed_checks + result.warnings))

        def _on_job_error(self, message):
            if getattr(self, "_job_is_detection", False):
                self.detect_score_lbl.setText("Cancelled; no result." if self._cancel_event.is_set() else "Analysis failed; no score.")
            if self._cancel_event.is_set():
                self.status_lbl.setText("Cancelled; output discarded.")
                return
            self.status_lbl.setText("Job failed; source preserved.")
            QMessageBox.critical(self, "LocalText", message)

        def _on_detect_clicked(self):
            if self._active_worker is not None:
                return
            text = self.detect_input.toPlainText()
            lang = str(self.detect_lang_combo.currentData())
            path = self.detector_path.text().strip()
            self.settings.setValue("detector_path", path)
            self._detect_snapshot = (text, lang)
            self.detect_score_lbl.setText("Loading / analyzing…")
            self.detect_details_lbl.setText("")
            cancel_event = self._cancel_event
            self._start_job(
                lambda: DetectionPipeline(model_dir=Path(path)).run_detection(
                    "gui-detect", 1, text, language=lang, cancel_event=cancel_event),
                self._on_detection_finished, "Analyzing locally on CPU…",
            )

        def _on_detection_finished(self, result):
            if self._cancel_event.is_set():
                self.detect_score_lbl.setText("Cancelled; no result.")
                self.status_lbl.setText("Cancelled; output discarded.")
                return
            if self._detect_snapshot != (self.detect_input.toPlainText(), self.detect_lang_combo.currentData()):
                self.detect_score_lbl.setText("Text or language changed; analyze again.")
                self.status_lbl.setText("Stale detection discarded.")
                return
            if result.raw_model_score is None:
                self.detect_score_lbl.setText(result.label.value)
                self.detect_details_lbl.setText(result.score_semantics)
            else:
                self.detect_score_lbl.setText(f"Raw model signal: {result.raw_model_score:.1f}/100 (uncalibrated)")
                self.detect_details_lbl.setText(
                    "Higher means more AI-like according to this model. This is not a percentage of AI-written "
                    "text or a probability of authorship. No local accuracy validation has been performed. "
                    f"Analyzed coverage: {result.analyzed_coverage_ratio:.0%}; windows: {len(result.window_results)}."
                )
            self.status_lbl.setText("Analysis complete.")

        def _on_accept_clicked(self):
            result = self.doc_state.latest_rewrite_result
            if (self._active_worker is None and self._pending_output is not None and result
                    and result.snapshot_revision == self.doc_state.revision and not self.doc_state.is_result_stale):
                self.src_edit.setPlainText(self._pending_output)
                self._clear_rewrite()
                self.status_lbl.setText("Changes accepted into source text.")

        def _on_reject_clicked(self):
            if self._active_worker is not None:
                self._on_cancel_clicked()
            self._clear_rewrite()
            self.status_lbl.setText("Rewrite rejected; original text preserved.")

        def _on_cancel_clicked(self):
            self._cancel_event.set()
            self._clear_rewrite()
            self.status_lbl.setText("Cancellation requested; waiting for the current model operation to stop…")
            self.cancel_btn.setEnabled(False)

        def _on_clear_session_clicked(self):
            if self._active_worker is not None:
                self._on_cancel_clicked()
            self.session_mgr.clear_session()
            self.src_edit.clear()
            self._clear_rewrite()
            self.detect_input.clear()
            self.detect_score_lbl.setText("Not analyzed")
            self.detect_details_lbl.clear()

        def closeEvent(self, event):
            if self._active_worker is not None:
                self._close_when_finished = True
                self._on_cancel_clicked()
                event.ignore()
            else:
                event.accept()

    return MainWindow()
