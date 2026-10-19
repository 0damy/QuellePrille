"""Regression tests for the formerly fake inference and unsafe acceptance paths."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from localtext.contracts import CandidateBlock, JobState, RewriteRequest, RewriteResult, RephraseMode, ChangeStrength
from localtext.detection.pipeline import DetectionPipeline
from localtext.detection.model_loader import ModelLoadError
from localtext.inference.ollama_client import OllamaHttpClient, InferenceCancelled, InferenceClientError
from localtext.rephrase.chunker import DocumentChunker
from localtext.rephrase.pipeline import RephrasePipeline, assemble_rewrite


class OllamaProtocolTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.info = {"capabilities": ["completion", "thinking"]}
        self.frames = [
            {"message": {"content": '"Actual rewritten prose."'}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": "stop"},
        ]
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.reply({"models": [{"name": "local:latest"}]})
            def reply(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, payload))
                if self.path == '/api/show':
                    self.reply(owner.info)
                else:
                    body = b''.join(json.dumps(item).encode() + b'\n' for item in owner.frames)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.client = OllamaHttpClient(f'http://127.0.0.1:{self.server.server_port}', model='local')

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_chat_protocol_preserves_quotes_and_system_message(self):
        result = self.client.generate_completion('source', 'system instruction')
        self.assertEqual(result, '"Actual rewritten prose."')
        path, payload = self.requests[-1]
        self.assertEqual(path, '/api/chat')
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': 'system instruction'})
        self.assertFalse(payload['think'])
        self.assertTrue(payload['stream'])
        self.assertEqual(payload['model'], 'local:latest')

    def test_missing_model_does_not_select_another(self):
        self.client.model = 'missing:8b'
        with self.assertRaisesRegex(InferenceClientError, 'not installed'):
            self.client.generate_completion('private text')
        self.assertEqual(self.requests, [])

    def test_cloud_model_refused_before_sending_source(self):
        self.info['remote_model'] = 'cloud-model'
        with self.assertRaisesRegex(InferenceClientError, 'Cloud models'):
            self.client.generate_completion('private text')
        self.assertEqual([path for path, _ in self.requests], ['/api/show'])

    def test_truncated_and_broken_streams_are_not_success(self):
        self.frames[-1]['done_reason'] = 'length'
        with self.assertRaisesRegex(InferenceClientError, 'before completion'):
            self.client.generate_completion('source')
        self.frames.pop()
        with self.assertRaisesRegex(InferenceClientError, 'incomplete response'):
            self.client.generate_completion('source')

    def test_cancellation_discards_streamed_text(self):
        event = threading.Event()
        with self.assertRaises(InferenceCancelled):
            self.client.generate_completion('source', cancel_event=event, token_callback=lambda _: event.set())

    def test_oversized_prompt_refused_before_generation(self):
        with self.assertRaisesRegex(InferenceClientError, 'context budget'):
            self.client.generate_completion('x' * 9000)
        self.assertEqual([path for path, _ in self.requests], ['/api/show'])

    def test_non_loopback_url_refused(self):
        with self.assertRaises(ValueError):
            OllamaHttpClient('https://example.com')


class RewriteSafetyTests(unittest.TestCase):
    def test_assembly_preserves_gaps_and_all_source_blocks(self):
        text = '\nFirst paragraph.\n\n\nSecond paragraph.\n'
        blocks = DocumentChunker(target_chunk_words=1).create_target_blocks(text)
        candidates = [CandidateBlock(b.block_id, 0, b.source_text.upper()) for b in blocks]
        result = RewriteResult('job', 1, JobState.COMPLETE, candidates)
        self.assertEqual(assemble_rewrite(text, blocks, result), text.upper())
        result.candidate_blocks.pop()
        with self.assertRaises(ValueError):
            assemble_rewrite(text, blocks, result)
        result.status = JobState.CANCELLED
        with self.assertRaises(ValueError):
            assemble_rewrite(text, blocks, result)

    def test_cancel_during_last_chunk_is_cancelled_not_complete(self):
        text = 'The original sentence must remain intact.'
        blocks = DocumentChunker().create_target_blocks(text)
        request = RewriteRequest('job', 1, 'test', RephraseMode.STANDARD, ChangeStrength.MEDIUM,
                                 target_blocks=tuple(blocks))
        event = threading.Event()
        def generator(*_):
            event.set()
            return 'Half a rewrite'
        result = RephrasePipeline().run_rephrase(request, generator, event)
        self.assertEqual(result.status, JobState.CANCELLED)
        self.assertEqual(result.candidate_blocks, [])

    def test_long_sentence_is_bounded_without_dropping_text(self):
        text = 'word ' * 1401
        blocks = DocumentChunker().create_target_blocks(text)
        self.assertTrue(all(len(block.source_text.split()) <= 600 for block in blocks))
        self.assertEqual(''.join(block.source_text for block in blocks), text)


class DetectionIntegrationTests(unittest.TestCase):
    def test_missing_weights_raise_instead_of_neutral_score(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = DetectionPipeline(model_dir=Path(directory))
            with self.assertRaises(ModelLoadError):
                pipeline.run_detection('job', 1, 'This is eligible English prose. ' * 40)

    def test_real_token_windows_cover_all_prose_and_use_original_offsets(self):
        class TinyAdapter:
            window_tokens = 80
            def tokenize(self, text):
                return list(range(len(text))), [(i, i + 1) for i in range(len(text))]
            def score_tokens(self, ids):
                self.calls.append(ids)
                return 2.0
            calls = []
        text = ('English prose words here. ' * 40) + '\n```excluded code```\n' + ('More prose. ' * 40)
        adapter = TinyAdapter()
        result = DetectionPipeline(detector=adapter).run_detection('job', 1, text)
        self.assertGreater(len(adapter.calls), 2)
        self.assertIsNone(result.score)
        self.assertEqual(result.calibration_id, '')
        self.assertGreater(result.raw_model_score, 80)
        covered = set()
        for window in result.window_results:
            self.assertNotIn('excluded code', window.span.slice_from(text))
            covered.update(range(window.span.start, window.span.end))
        expected = {i for span in result.eligible_ranges for i in range(span.start, span.end)}
        self.assertEqual(covered, expected)
