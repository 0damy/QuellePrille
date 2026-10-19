"""Ollama-native HTTP client for local inference via running ollama serve.

Adheres strictly to Section 6, NFR-03, REP-08, AT-02, and AT-10.
Uses the Ollama REST API (/api/generate, /api/chat, /api/tags) rather than
the llama-server OpenAI-compat endpoints, which Ollama does not implement
on the same paths.

All connections are to the loopback only.  Proxy inheritance is disabled.
"""

from __future__ import annotations

import json
import threading
from typing import Callable, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from localtext.inference.llama_client import InferenceClientError


# --------------------------------------------------------------------------- #
#  Ollama client                                                               #
# --------------------------------------------------------------------------- #

class OllamaHttpClient:
    """Communicates with a running `ollama serve` daemon via its native REST API."""

    # Default model name used when none is specified by the caller.
    # Callers should prefer passing the model name explicitly.
    DEFAULT_MODEL = "qwen3:8b"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: Optional[str] = None,
        timeout_seconds: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds

        # Disable proxy inheritance for loopback calls (Section 6)
        self.session = requests.Session()
        self.session.trust_env = False

        retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    # ----------------------------------------------------------------------- #
    #  Probing helpers                                                          #
    # ----------------------------------------------------------------------- #

    def is_reachable(self) -> bool:
        """Return True if ollama daemon is listening and its /api/tags endpoint responds."""
        try:
            resp = self.session.get(f"{self.base_url}/api/tags", timeout=2.0)
            return resp.ok
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Return a list of model names available in the local ollama store."""
        try:
            resp = self.session.get(f"{self.base_url}/api/tags", timeout=5.0)
            if not resp.ok:
                return []
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def _pick_model(self, preferred: Optional[str] = None) -> str:
        """Return the best available model, falling back to the first available one."""
        candidates = preferred or self.model
        available = self.list_models()
        if not available:
            # Daemon is reachable but no models yet — the caller will fail gracefully
            return candidates

        # Exact match first
        for m in available:
            if m == candidates:
                return m
        # Prefix match (e.g. "qwen3:8b" matches "qwen3:8b-instruct-q6_K")
        prefix = candidates.split(":")[0].lower()
        for m in available:
            if m.lower().startswith(prefix):
                return m
        # Fall back to first available model
        return available[0]

    # ----------------------------------------------------------------------- #
    #  Text generation                                                          #
    # ----------------------------------------------------------------------- #

    def generate_completion(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        cancel_event: Optional[threading.Event] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Generate text using Ollama /api/generate (non-streaming or streaming).

        Falls back to /api/chat if the response schema looks like a chat model.
        """
        model = self._pick_model()

        # Build the full prompt string for /api/generate (instruct style)
        if system_prompt:
            full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        else:
            full_prompt = prompt

        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": bool(token_callback),
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "stop": ["<<<DATA_END>>>", "</s>", "<|im_end|>", "<|end|>"],
            },
        }

        url = f"{self.base_url}/api/generate"
        try:
            if not token_callback:
                resp = self.session.post(url, json=payload, timeout=self.timeout_seconds)

                if resp.status_code == 404:
                    # Try /api/chat fallback
                    return self._chat_completion(
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                if not resp.ok:
                    raise InferenceClientError(
                        f"Ollama error {resp.status_code}: {resp.text[:300]}"
                    )

                data = resp.json()
                return self._clean_output(data.get("response", ""))

            # Streaming mode
            collected: List[str] = []
            with self.session.post(
                url, json=payload, stream=True, timeout=self.timeout_seconds
            ) as stream_resp:
                if not stream_resp.ok:
                    raise InferenceClientError(
                        f"Ollama stream error {stream_resp.status_code}"
                    )
                for raw_line in stream_resp.iter_lines():
                    if cancel_event and cancel_event.is_set():
                        break
                    if raw_line:
                        try:
                            chunk = json.loads(raw_line.decode("utf-8"))
                            token = chunk.get("response", "")
                            if token:
                                collected.append(token)
                                if token_callback:
                                    token_callback(token)
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            pass

            return self._clean_output("".join(collected))

        except requests.exceptions.RequestException as exc:
            raise InferenceClientError(
                f"Connection failure to ollama daemon: {exc}"
            ) from exc

    def _chat_completion(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Use /api/chat endpoint (chat-oriented Ollama models)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        url = f"{self.base_url}/api/chat"
        resp = self.session.post(url, json=payload, timeout=self.timeout_seconds)
        if not resp.ok:
            raise InferenceClientError(
                f"Ollama /api/chat error {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return self._clean_output(content)

    def _clean_output(self, text: str) -> str:
        """Strip internal reasoning tags or stray markdown fences from output."""
        cleaned = text.strip()
        # Remove <think>...</think> traces (e.g. Qwen3 internal reasoning)
        if "<think>" in cleaned and "</think>" in cleaned:
            parts = cleaned.split("</think>", 1)
            cleaned = parts[1].strip()
        # Strip outer quotes added spuriously by some models
        if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned
