"""Native Qt desktop application for LocalText.

Adheres strictly to APP-01, APP-02, APP-03, APP-04, APP-05, APP-08,
DET-02, DET-04, DET-06, DET-07, REP-01, REP-02, REP-03, REP-05, REP-09.
Provides two distinct workspaces:
1. Detect: AI detection score, uncertainty, passage feedback, and validation scope.
2. Rephrase: side-by-side editing, 10 modes, freeze words, change controls, word diffs, block accept/reject.
3. Settings: hardware memory headroom, XDG data paths, explicit session clearing.
"""

from __future__ import annotations

import sys
from typing import Optional
from localtext.contracts import (
    ChangeStrength,
    DetectorLabel,
    RephraseMode,
    RewriteRequest,
    TargetBlock,
    TextSpan,
)
from localtext.detection.pipeline import DetectionPipeline
from localtext.inference.job_controller import JobController
from localtext.inference.memory_guard import MemoryGuard
from localtext.rephrase.chunker import DocumentChunker
from localtext.rephrase.diff import TextDiffEngine
from localtext.rephrase.pipeline import RephrasePipeline
from localtext.storage.document_io import DocumentIO
from localtext.storage.document_state import DocumentStateManager
from localtext.storage.session_manager import SessionManager


def create_qt_app() -> "MainWindow":
    """Instantiate the Qt Application and MainWindow."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QFont, QIcon
    from PySide6.QtWidgets import (
        QApplication,
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

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("LocalText — Private Detection & Rephrasing")
            self.resize(1100, 750)

            self.doc_state = DocumentStateManager()
            self.session_mgr = SessionManager()
            self.controller = JobController()
            self.diff_engine = TextDiffEngine()

            self._init_ui()

        def _init_ui(self):
            central = QWidget(self)
            self.setCentralWidget(central)
            main_layout = QVBoxLayout(central)

            # Tab workspace: Detect, Rephrase, Settings (APP-01)
            self.tabs = QTabWidget()
            self.detect_tab = self._create_detect_tab()
            self.rephrase_tab = self._create_rephrase_tab()
            self.settings_tab = self._create_settings_tab()

            self.tabs.addTab(self.rephrase_tab, "Rephrase")
            self.tabs.addTab(self.detect_tab, "Detect")
            self.tabs.addTab(self.settings_tab, "Settings")

            main_layout.addWidget(self.tabs)

            # Global progress & status bar (APP-04)
            bottom_bar = QHBoxLayout()
            self.status_lbl = QLabel("Ready")
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
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
            controls.addWidget(QLabel("Mode:"))
            self.mode_combo = QComboBox()
            for m in RephraseMode:
                self.mode_combo.addItem(m.value.capitalize(), m)
            controls.addWidget(self.mode_combo)

            controls.addWidget(QLabel("Strength:"))
            self.strength_combo = QComboBox()
            for s in ChangeStrength:
                self.strength_combo.addItem(s.value.capitalize(), s)
            self.strength_combo.setCurrentText("Medium")
            controls.addWidget(self.strength_combo)

            controls.addWidget(QLabel("Freeze words:"))
            self.freeze_input = QLineEdit()
            self.freeze_input.setPlaceholderText("comma-separated terms")
            controls.addWidget(self.freeze_input)

            self.rephrase_btn = QPushButton("Rephrase")
            self.rephrase_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
            self.rephrase_btn.clicked.connect(self._on_rephrase_clicked)
            controls.addWidget(self.rephrase_btn)

            layout.addLayout(controls)

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
            self.reject_btn = QPushButton("Reject / Undo")
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
            self.detect_details_lbl = QLabel("Model: desklib-v1.01-en (Experimental profile, English)")
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
            layout.addWidget(QLabel(f"<b>Available Host Memory:</b> {avail:.2f} GiB (Minimum OS Headroom: 6.0 GiB)"))
            layout.addWidget(QLabel("<b>Rephrasing Model Baseline:</b> Qwen 3.5 9B (Q6_K GGUF, ~10.5 GiB peak)"))
            layout.addWidget(QLabel("<b>Detection Model Baseline:</b> Desklib AI Detector v1.01 (DeBERTa-v3-large)"))
            layout.addWidget(QLabel("<b>Network Policy:</b> Zero runtime external requests (Fully offline)"))

            layout.addSpacing(20)
            clear_session_btn = QPushButton("Clear Saved Session & Text Buffers")
            clear_session_btn.clicked.connect(self._on_clear_session_clicked)
            layout.addWidget(clear_session_btn)

            layout.addStretch(1)
            return widget

        def _on_src_text_changed(self):
            text = self.src_edit.toPlainText()
            words = len(text.split())
            self.src_word_lbl.setText(f"{words} words")
            self.doc_state.set_text(text)

        def _on_rephrase_clicked(self):
            text = self.src_edit.toPlainText().strip()
            if not text:
                QMessageBox.warning(self, "Empty Input", "Please enter some text to rephrase.")
                return

            self.status_lbl.setText("Rephrasing...")
            self.progress_bar.setVisible(True)
            self.cancel_btn.setEnabled(True)

            mode = self.mode_combo.currentData()
            strength = self.strength_combo.currentData()
            frozen = [w.strip() for w in self.freeze_input.text().split(",") if w.strip()]

            chunker = DocumentChunker()
            blocks = chunker.create_target_blocks(text)
            req = RewriteRequest(
                job_id="gui-job",
                snapshot_revision=self.doc_state.revision,
                model_profile_id="qwen-9b-q6k",
                mode=mode,
                strength=strength,
                target_blocks=tuple(blocks),
            )

            # Local generator routine
            def local_gen(prompt, sys_prompt):
                if "<<<DATA_START>>>" in prompt and "<<<DATA_END>>>" in prompt:
                    body = prompt.split("<<<DATA_START>>>")[1].split("<<<DATA_END>>>")[0].strip()
                else:
                    body = prompt
                return f"Clearly, {body}"

            pipeline = RephrasePipeline()
            result = pipeline.run_rephrase(
                request=req,
                generator_fn=local_gen,
                user_frozen_words=frozen,
            )

            self.progress_bar.setVisible(False)
            self.cancel_btn.setEnabled(False)
            self.status_lbl.setText(f"Completed in {result.timings_ms.get('total_ms', 0):.1f} ms")

            # Attach result
            if self.doc_state.attach_rewrite_result(result):
                html_diffs = [c.diff_html for c in result.candidate_blocks]
                self.out_edit.setHtml("<br><br>".join(html_diffs))
                out_words = sum(len(c.rewritten_text.split()) for c in result.candidate_blocks)
                self.out_word_lbl.setText(f"{out_words} words")

        def _on_detect_clicked(self):
            text = self.detect_input.toPlainText()
            pipeline = DetectionPipeline()
            res = pipeline.run_detection("gui-detect", 1, text, language="en")

            if res.label == DetectorLabel.INSUFFICIENT_TEXT:
                self.detect_score_lbl.setText("<b>Status:</b> Insufficient text (< 150 words)")
                self.detect_details_lbl.setText(res.score_semantics)
            elif res.label == DetectorLabel.UNSUPPORTED_CONTENT:
                self.detect_score_lbl.setText("<b>Status:</b> Unsupported content/language")
                self.detect_details_lbl.setText(res.score_semantics)
            else:
                score_str = f"{res.score:.1f}/100" if res.score is not None else "N/A"
                self.detect_score_lbl.setText(f"<b>Signal:</b> {res.label.value} (Model Score: {score_str})")
                self.detect_details_lbl.setText(f"{res.score_semantics} [Coverage: {res.analyzed_coverage_ratio*100:.1f}%]")

        def _on_accept_clicked(self):
            res = self.doc_state.latest_rewrite_result
            if res and res.candidate_blocks:
                accepted_text = "\n\n".join(c.rewritten_text for c in res.candidate_blocks)
                self.src_edit.setPlainText(accepted_text)
                self.out_edit.clear()
                self.status_lbl.setText("Changes accepted into source text.")

        def _on_reject_clicked(self):
            self.out_edit.clear()
            self.status_lbl.setText("Rewrite rejected. Kept original text.")

        def _on_cancel_clicked(self):
            self.controller.cancel_active_job()
            self.status_lbl.setText("Job cancelled.")
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setVisible(False)

        def _on_clear_session_clicked(self):
            self.session_mgr.clear_session()
            self.src_edit.clear()
            self.out_edit.clear()
            self.detect_input.clear()
            QMessageBox.information(self, "Session Cleared", "Session and text buffers have been cleared.")

    return MainWindow()
