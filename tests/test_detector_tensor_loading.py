"""Exercise real tensor loading/inference with a tiny synthetic local checkpoint.

This verifies plumbing, not accuracy of the production Desklib checkpoint.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from localtext.detection.model_loader import LocalDesklibDetector, ModelLoadError

HAS_DEPS = all(importlib.util.find_spec(m) for m in ('torch', 'transformers', 'safetensors'))


@unittest.skipUnless(HAS_DEPS, 'Install detector extra for tensor integration tests')
class TensorLoadingTests(unittest.TestCase):
    def test_local_checkpoint_forward_and_strict_missing_tensor_rejection(self):
        import torch
        from safetensors.torch import save_file
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from tokenizers.processors import TemplateProcessing
        from transformers import AutoModel, DebertaV2Config, PreTrainedTokenizerFast
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = DebertaV2Config(vocab_size=8, hidden_size=16, num_hidden_layers=1,
                                     num_attention_heads=2, intermediate_size=24,
                                     max_position_embeddings=512, conv_kernel_size=0)
            config.save_pretrained(folder)
            tokenizer = Tokenizer(WordLevel({'[UNK]': 0, '[PAD]': 1, '[CLS]': 2, '[SEP]': 3,
                                            'some': 4, 'text': 5, 'different': 6, '.': 7}, unk_token='[UNK]'))
            tokenizer.pre_tokenizer = Whitespace()
            tokenizer.post_processor = TemplateProcessing(single='[CLS] $A [SEP]',
                                                           special_tokens=[('[CLS]', 2), ('[SEP]', 3)])
            fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token='[UNK]', pad_token='[PAD]',
                                          cls_token='[CLS]', sep_token='[SEP]')
            fast.save_pretrained(folder)
            encoder = AutoModel.from_config(config).eval()
            head = torch.nn.Linear(16, 1).eval()
            state = {'model.' + key: value for key, value in encoder.state_dict().items()}
            state.update({'classifier.' + key: value for key, value in head.state_dict().items()})
            save_file(state, folder / 'model.safetensors')
            # This fixture is only a few KB, so the production multi-GB budget is irrelevant.
            with patch('localtext.inference.memory_guard.MemoryGuard.enforce_admission'):
                detector = LocalDesklibDetector(folder)
                ids, offsets = detector.tokenize('some text')
                self.assertEqual(offsets, [(0, 4), (5, 9)])
                score = detector.score_tokens(ids)
                full_ids = fast.build_inputs_with_special_tokens(ids)
                tensor = torch.tensor([full_ids])
                with torch.inference_mode():
                    expected = head(encoder(tensor, attention_mask=torch.ones_like(tensor))[0].mean(1)).item()
                self.assertAlmostEqual(score, expected, places=5)
                state.pop('model.embeddings.word_embeddings.weight')
                save_file(state, folder / 'model.safetensors')
                with self.assertRaises(ModelLoadError):
                    LocalDesklibDetector(folder)
