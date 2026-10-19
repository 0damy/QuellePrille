"""Authenticated loopback HTTP client for local inference server.

Adheres strictly to Section 6, NFR-03, REP-08, AT-02, and AT-10.
Disables environment proxy inheritance for loopback calls.
Authenticates using Bearer token from runtime auth manager.
Supports streaming, timeout, and cancellation token abort.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from localtext.inference.runtime_auth import RuntimeAuthManager


class InferenceClientError(RuntimeError):
    """Raised on generation errors or authentication rejection."""
    pass


class LlamaHttpClient:
    """Communicates directly with loopback llama-server using authenticated requests."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        auth_manager: Optional[RuntimeAuthManager] = None,
        timeout_seconds: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_manager = auth_manager or RuntimeAuthManager()
        self.timeout_seconds = timeout_seconds

        # Configure session with proxy inheritance disabled for loopback calls (Section 6)
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore HTTP_PROXY, HTTPS_PROXY, etc.

        retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def is_reachable(self) -> bool:
        """Check if local inference server is accepting loopback connections."""
        try:
            resp = self.session.get(f"{self.base_url}/health", timeout=1.0)
            if resp.ok:
                return True
        except Exception:
            pass

        # Try base connection
        try:
            resp = self.session.get(self.base_url, timeout=1.0)
            return True
        except Exception:
            return False

    def generate_completion(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1024,
        cancel_event: Optional[threading.Event] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Send completion request to local server with authentication and streaming (REP-08, AT-02)."""
        headers = self.auth_manager.get_auth_headers()
        url = f"{self.base_url}/completion"

        payload = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "n_predict": max_tokens,
            "stream": bool(token_callback),
            "stop": ["<<<DATA_END>>>", "</s>", "<|im_end|>"],
        }

        try:
            if not token_callback:
                resp = self.session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code == 404:
                    # Fallback to OpenAI-compatible chat endpoint
                    chat_url = f"{self.base_url}/v1/chat/completions"
                    chat_payload = {
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    resp = self.session.post(
                        chat_url,
                        headers=headers,
                        json=chat_payload,
                        timeout=self.timeout_seconds,
                    )
                    if resp.ok:
                        data = resp.json()
                        choices = data.get("choices", [{}])
                        msg = choices[0].get("message", {}).get("content", "")
                        return self._clean_output(msg)

                if resp.status_code == 401:
                    raise InferenceClientError("Request rejected: Unauthorized (AT-02). Invalid or missing API secret.")
                if not resp.ok:
                    raise InferenceClientError(f"Inference error {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                return self._clean_output(data.get("content", ""))

            # Streaming mode
            collected: List[str] = []
            with self.session.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.timeout_seconds,
            ) as stream_resp:
                if stream_resp.status_code == 401:
                    raise InferenceClientError("Request rejected: Unauthorized (AT-02).")
                if not stream_resp.ok:
                    raise InferenceClientError(f"Stream error {stream_resp.status_code}")

                for line in stream_resp.iter_lines():
                    if cancel_event and cancel_event.is_set():
                        # Acknowledge cancellation immediately
                        break
                    if line:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data: "):
                            raw_chunk = decoded[6:]
                            try:
                                chunk_json = json.loads(raw_chunk)
                                chunk_text = chunk_json.get("content", "")
                                collected.append(chunk_text)
                                if token_callback:
                                    token_callback(chunk_text)
                            except json.JSONDecodeError:
                                pass

            return self._clean_output("".join(collected))

        except requests.exceptions.RequestException as e:
            raise InferenceClientError(f"Connection failure to local inference listener: {e}")

    def _clean_output(self, text: str) -> str:
        """Strip internal reasoning tags or stray markdown fences from output."""
        cleaned = text.strip()
        # Remove any internal <think>...</think> traces if present
        if "<think>" in cleaned and "</think>" in cleaned:
            parts = cleaned.split("</think>", 1)
            cleaned = parts[1].strip()
        # Strip outer quotes if artificially added
        if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned
