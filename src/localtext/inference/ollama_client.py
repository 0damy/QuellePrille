"""Explicit local Ollama chat inference. No substitution or cloud fallback."""
from __future__ import annotations

import json
import threading
from typing import Callable, Optional
from urllib.parse import urlsplit
import requests
from localtext.inference.llama_client import InferenceClientError


class InferenceCancelled(InferenceClientError):
    """A cancelled response must never be used as a complete rewrite."""


def check_cancelled(event: Optional[threading.Event]) -> None:
    if event is not None and event.is_set():
        raise InferenceCancelled("Cancelled; output discarded.")


class OllamaHttpClient:
    DEFAULT_MODEL = "qwen3:8b"

    def __init__(self, base_url="http://127.0.0.1:11434", model=None, timeout_seconds=120.0):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or url.username or url.password or url.path not in {"", "/"}
                or url.query or url.fragment):
            raise ValueError("Ollama must use a loopback HTTP address.")
        self.base_url = base_url.rstrip("/")
        self.model = (model or self.DEFAULT_MODEL).strip()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def is_reachable(self):
        try:
            self.list_models()
            return True
        except InferenceClientError:
            return False

    def list_models(self):
        try:
            with self.session.get(f"{self.base_url}/api/tags", timeout=5,
                                  allow_redirects=False) as response:
                if response.status_code != 200:
                    raise InferenceClientError(f"Ollama model listing failed (HTTP {response.status_code}).")
                return [entry["name"] for entry in response.json()["models"]]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise InferenceClientError("Cannot read local Ollama models. Start Ollama and check Settings.") from exc

    def _pick_model(self, preferred=None):
        requested = preferred or self.model
        available = self.list_models()
        canonical = requested if ":" in requested else requested + ":latest"
        if canonical not in available:
            raise InferenceClientError(
                f"Model '{canonical}' is not installed. Choose its exact name from `ollama list` in Settings."
            )
        return canonical

    def generate_completion(self, prompt: str, system_prompt: str = "", temperature=0.3,
                            max_tokens=2048, cancel_event=None,
                            token_callback: Optional[Callable[[str], None]] = None) -> str:
        check_cancelled(cancel_event)
        model = self._pick_model()
        try:
            # A local daemon can also proxy cloud models. Reject those before sending text.
            with self.session.post(f"{self.base_url}/api/show", json={"model": model},
                                   timeout=10, allow_redirects=False) as info_response:
                if info_response.status_code != 200:
                    raise InferenceClientError("Cannot inspect the selected Ollama model.")
                info = info_response.json()
            if info.get("remote_model") or info.get("remote_host") or "cloud" in model.lower():
                raise InferenceClientError("Cloud models are disabled. Select a downloaded local model.")
            # Conservative byte budget leaves room for output and the model template.
            # Refuse oversized requests rather than letting the server truncate source.
            limits = [int(value) for key, value in info.get("model_info", {}).items()
                      if key.endswith(".context_length") and isinstance(value, (int, float))]
            context_size = min([8192] + limits)
            input_budget = context_size - max_tokens - 512
            if len((system_prompt + prompt).encode("utf-8")) > input_budget:
                raise InferenceClientError("Passage plus instructions exceed the conservative context budget. Use a shorter passage.")
            check_cancelled(cancel_event)
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": prompt}],
                "stream": True,
                "keep_alive": 0,
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": context_size},
            }
            if "thinking" in info.get("capabilities", []):
                payload["think"] = False
            pieces = []
            complete = False
            with self.session.post(f"{self.base_url}/api/chat", json=payload, stream=True,
                                   timeout=(5, self.timeout_seconds), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise InferenceClientError(f"Ollama generation failed (HTTP {response.status_code}).")
                for line in response.iter_lines(chunk_size=1):
                    check_cancelled(cancel_event)
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise InferenceClientError("Ollama reported a generation error; output discarded.")
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        pieces.append(content)
                        if token_callback:
                            token_callback(content)
                    if chunk.get("done"):
                        if chunk.get("done_reason") != "stop":
                            raise InferenceClientError("Generation stopped before completion. Try a shorter passage.")
                        complete = True
                        break
            check_cancelled(cancel_event)
            output = "".join(pieces).strip()
            if not complete or not output:
                raise InferenceClientError("Ollama returned an empty or incomplete response; output discarded.")
            if "<think>" in output or "</think>" in output:
                raise InferenceClientError("The model returned reasoning instead of a clean rewrite. Select a non-thinking model.")
            return output
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            check_cancelled(cancel_event)
            raise InferenceClientError("Local Ollama request failed or timed out; output discarded.") from exc
