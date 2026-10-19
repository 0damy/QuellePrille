"""Offscreen Qt tests for thread lifetime, stale results and acceptance safety."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtTest import QTest
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

from localtext.contracts import CandidateBlock, RewriteResult, JobState
from localtext.rephrase.chunker import DocumentChunker


@unittest.skipUnless(QT_AVAILABLE, 'Install the gui extra for Qt tests')
class GuiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from localtext.gui.main_window import create_qt_app
        self.window = create_qt_app()
        self.messages = patch.object(QMessageBox, 'critical')
        self.critical = self.messages.start()

    def tearDown(self):
        if self.window._active_worker is not None:
            self.window._on_cancel_clicked()
            self.pump_until(lambda: self.window._active_worker is None)
        self.window.close()
        self.messages.stop()

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(predicate())

    def attach_result(self):
        w = self.window
        w.src_edit.setPlainText('First paragraph.\n\n\nSecond paragraph.\n')
        w._rewrite_source = w.src_edit.toPlainText()
        w._rewrite_blocks = DocumentChunker(target_chunk_words=1).create_target_blocks(w._rewrite_source)
        result = RewriteResult('job', w.doc_state.revision, JobState.COMPLETE,
                               [CandidateBlock(b.block_id, 0, b.source_text.upper()) for b in w._rewrite_blocks])
        w._on_rephrase_finished(result)
        return result

    def test_accept_preserves_separator_and_reject_cannot_be_accepted(self):
        w = self.window
        self.attach_result()
        expected = w.src_edit.toPlainText().upper()
        w._on_accept_clicked()
        self.assertEqual(w.src_edit.toPlainText(), expected)
        self.attach_result()
        source = w.src_edit.toPlainText()
        w._on_reject_clicked()
        w._on_accept_clicked()
        self.assertEqual(w.src_edit.toPlainText(), source)
        self.assertIsNone(w.doc_state.latest_rewrite_result)

    def test_edit_invalidates_pending_result(self):
        self.attach_result()
        self.window.src_edit.setPlainText('Newer text')
        self.window._on_accept_clicked()
        self.assertEqual(self.window.src_edit.toPlainText(), 'Newer text')
        self.assertIsNone(self.window._pending_output)

    def test_cancel_keeps_worker_alive_and_blocks_new_job_until_stopped(self):
        w = self.window
        w.src_edit.setPlainText('A sentence to rewrite.')
        started = threading.Event()
        release = threading.Event()
        def generate(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            return 'A rewritten sentence.'
        with patch('localtext.inference.ollama_client.OllamaHttpClient.generate_completion', side_effect=generate):
            w._on_rephrase_clicked()
            self.pump_until(started.is_set)
            original_worker = w._active_worker
            w._on_cancel_clicked()
            w._on_rephrase_clicked()
            self.assertIs(w._active_worker, original_worker)
            self.assertFalse(w.rephrase_btn.isEnabled())
            self.assertFalse(w.detect_btn.isEnabled())
            release.set()
            self.pump_until(lambda: w._active_worker is None)
        self.assertEqual(w.src_edit.toPlainText(), 'A sentence to rewrite.')
        self.assertIsNone(w._pending_output)
        self.assertFalse(w.accept_btn.isEnabled())
        self.critical.assert_not_called()

    def test_no_backend_error_never_creates_fake_rewrite(self):
        w = self.window
        w.src_edit.setPlainText('A lot of text cannot be rewritten without a model.')
        with patch('localtext.inference.ollama_client.OllamaHttpClient.generate_completion',
                   side_effect=RuntimeError('Ollama unavailable')):
            w._on_rephrase_clicked()
            self.pump_until(lambda: w._active_worker is None)
        self.assertIsNone(w._pending_output)
        self.assertFalse(w.accept_btn.isEnabled())
        self.critical.assert_called_once()

    def test_close_during_generation_defers_destruction(self):
        w = self.window
        w.show()
        started, release = threading.Event(), threading.Event()
        def generate(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            return 'A rewritten sentence.'
        w.src_edit.setPlainText('A sentence to rewrite.')
        with patch('localtext.inference.ollama_client.OllamaHttpClient.generate_completion', side_effect=generate):
            w._on_rephrase_clicked()
            self.pump_until(started.is_set)
            w.close()
            self.assertTrue(w.isVisible())
            self.assertIsNotNone(w._active_worker)
            release.set()
            self.pump_until(lambda: w._active_worker is None)
            self.assertFalse(w.isVisible())
