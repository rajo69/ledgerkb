"""The OpenAI-compatible adapter — one client for roughly 95% of providers.

``/chat/completions`` and ``/embeddings`` are the two endpoints nearly every
vendor speaks: OpenRouter, OpenAI, Azure, Groq, Together, Fireworks, DeepInfra,
Mistral, DeepSeek, and every local server worth using (Ollama, vLLM,
llama.cpp, LM Studio, TGI, TEI, Infinity). They differ in ``base_url`` and
``model``, not in code, which is why this file is the only place an HTTP call
to a model provider is allowed to live.

Two things are deliberate and load-bearing:

* **No tools are ever sent unless a caller explicitly asks.** Extraction runs
  through here and its anti-injection control is architectural: untrusted
  document text must never reach a context that can act. Passing tools stays
  possible, but it is never the default and never implicit.
* **Capabilities are probed once per (base_url, model) and cached**, then
  structured output degrades ``json_schema`` → ``json_object`` → parsed
  markdown. A routed model that cannot do strict schemas is common on
  aggregators, and the alternative to degrading is crashing.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ledgerkb.core.errors import ProviderError
from ledgerkb.core.ports import Capabilities

T = TypeVar("T", bound=BaseModel)

RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_FENCE = re.compile(r"[`]{3}(?:json)?\s*(.*?)[`]{3}", re.DOTALL)

_CAPABILITIES: dict[tuple[str, str], Capabilities] = {}
"""Probe results, cached per endpoint+model for the life of the process."""


def _api_key(env_var: str, *, required: bool) -> str:
    key = os.environ.get(env_var, "")
    if not key and required:
        raise ProviderError(
            f"{env_var} is not set. Either export it, or point the provider at a "
            "local endpoint that needs no key (Ollama, vLLM, TEI)."
        )
    return key


class _Endpoint:
    """Shared HTTP plumbing: auth, retries, and errors that name the provider."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key_env: str = "OPENROUTER_API_KEY",
        timeout_s: float = 120.0,
        max_retries: int = 3,
        requires_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.max_retries = max_retries
        headers = {"Content-Type": "application/json"}
        key = _api_key(api_key_env, required=requires_key)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        # Attribution on OpenRouter; harmless everywhere else.
        headers["HTTP-Referer"] = "https://github.com/rajo69/ledgerkb"
        headers["X-Title"] = "ledgerkb"
        self.client = client or httpx.Client(timeout=timeout_s, headers=headers)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last = exc
            else:
                if response.status_code < 400:
                    try:
                        body: dict[str, Any] = response.json()
                    except ValueError as exc:
                        raise ProviderError(
                            f"{url} returned {response.status_code} with a non-JSON body"
                        ) from exc
                    return body
                if response.status_code not in RETRY_STATUS:
                    raise ProviderError(
                        f"{url} returned {response.status_code}: {response.text[:400]}"
                    )
                last = ProviderError(
                    f"{url} returned {response.status_code}: {response.text[:200]}"
                )
            if attempt + 1 < self.max_retries:
                time.sleep(2**attempt * 0.5)
        raise ProviderError(f"{url} failed after {self.max_retries} attempts: {last}")

    def close(self) -> None:
        self.client.close()


class OpenAICompatChat:
    """Implements :class:`ledgerkb.core.ports.ChatModel`."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        *,
        api_key_env: str = "OPENROUTER_API_KEY",
        temperature: float = 0.0,
        timeout_s: float = 120.0,
        requires_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = model
        self.temperature = temperature
        self.endpoint = _Endpoint(
            base_url,
            api_key_env=api_key_env,
            timeout_s=timeout_s,
            requires_key=requires_key,
            client=client,
        )
        self.usage: list[dict[str, int]] = []
        """Per-call token counts, for the run record and the budget guard."""

    # --- completion ----------------------------------------------------------

    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> str:
        body = self._chat(messages, kw)
        return self._first_message(body).get("content") or ""

    def structured(self, messages: list[dict[str, Any]], schema: type[T], **kw: Any) -> T:
        """Constrained output, degrading through whatever the endpoint supports."""
        modes = ["json_schema", "json_object", "text"]
        if not self.capabilities().structured_output:
            modes = ["json_object", "text"]

        errors: list[str] = []
        for mode in modes:
            payload = dict(kw)
            turns = messages
            if mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": schema.model_json_schema(),
                    },
                }
            elif mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
                turns = _with_schema_hint(messages, schema)

            try:
                raw = self.complete(turns, **payload)
                return schema.model_validate_json(_json_fragment(raw))
            except (ProviderError, ValidationError, ValueError) as exc:
                errors.append(f"{mode}: {type(exc).__name__}: {exc}")

        raise ProviderError(
            f"{self.name} could not produce a valid {schema.__name__}. " + " | ".join(errors)
        )

    def _chat(self, messages: list[dict[str, Any]], kw: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.name,
            "messages": messages,
            "temperature": kw.pop("temperature", self.temperature),
        }
        # Tools are opt-in and never implicit — see the module docstring.
        payload.update({k: v for k, v in kw.items() if v is not None})
        body = self._post_chat(payload)
        if usage := body.get("usage"):
            self.usage.append(
                {
                    "input_tokens": int(usage.get("prompt_tokens", 0)),
                    "output_tokens": int(usage.get("completion_tokens", 0)),
                }
            )
        return body

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.endpoint.post("/chat/completions", payload)

    @staticmethod
    def _first_message(body: dict[str, Any]) -> dict[str, Any]:
        try:
            message: dict[str, Any] = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"Response carried no message: {json.dumps(body)[:300]}"
            ) from exc
        return message

    # --- capabilities --------------------------------------------------------

    def capabilities(self) -> Capabilities:
        """Probed once per (base_url, model), then cached.

        "Works with any provider" is only true if the differences are
        discovered rather than assumed.
        """
        key = (self.endpoint.base_url, self.name)
        if key in _CAPABILITIES:
            return _CAPABILITIES[key]

        probe_schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        caps = Capabilities(structured_output=True, tools=False)
        try:
            self._post_chat(
                {
                    "model": self.name,
                    "messages": [{"role": "user", "content": "Reply with ok true."}],
                    "max_tokens": 16,
                    "temperature": 0.0,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "Probe",
                            "strict": True,
                            "schema": probe_schema,
                        },
                    },
                }
            )
        except ProviderError:
            caps = Capabilities(structured_output=False, tools=False)

        _CAPABILITIES[key] = caps
        return caps

    def close(self) -> None:
        self.endpoint.close()


class OpenAICompatEmbedder:
    """Implements :class:`ledgerkb.core.ports.Embedder`."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        *,
        dimensions: int = 1024,
        api_key_env: str = "OPENROUTER_API_KEY",
        batch_size: int = 64,
        timeout_s: float = 120.0,
        requires_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.endpoint = _Endpoint(
            base_url,
            api_key_env=api_key_env,
            timeout_s=timeout_s,
            requires_key=requires_key,
            client=client,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            body = self.endpoint.post("/embeddings", {"model": self.name, "input": batch})
            try:
                rows = sorted(body["data"], key=lambda d: d["index"])
            except (KeyError, TypeError) as exc:
                raise ProviderError(
                    f"Embedding response carried no data: {json.dumps(body)[:300]}"
                ) from exc
            for row in rows:
                vector = [float(x) for x in row["embedding"]]
                if len(vector) != self.dimensions:
                    raise ProviderError(
                        f"{self.name} returned {len(vector)}-dimensional vectors but the "
                        f"store is configured for {self.dimensions}. The dimension is "
                        "locked after the first index build; fix the config, or run "
                        "lkb reindex --confirm to rebuild deliberately."
                    )
                out.append(vector)
        return out

    def close(self) -> None:
        self.endpoint.close()


def _with_schema_hint(
    messages: list[dict[str, Any]], schema: type[BaseModel]
) -> list[dict[str, Any]]:
    """Spell the schema out for endpoints that only offer a generic JSON mode."""
    hint = (
        "Reply with a single JSON object and nothing else. It must validate "
        f"against this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )
    return [*messages, {"role": "system", "content": hint}]


def _json_fragment(raw: str) -> str:
    """Pull the JSON object out of a reply that may be wrapped in prose."""
    text = raw.strip()
    if match := _FENCE.search(text):
        text = match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in reply: {raw[:200]!r}")
    return text[start : end + 1]


__all__ = ["OpenAICompatChat", "OpenAICompatEmbedder"]
