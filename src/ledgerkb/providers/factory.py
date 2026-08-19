"""Build providers from config — the one place a provider name becomes a class.

Everything else in the library takes an ``Embedder`` or a ``ChatModel`` and
never asks where it came from. That is what makes the escape hatch real: pass
your own implementation of the Protocol and nothing downstream notices.
"""

from __future__ import annotations

from ledgerkb.core.config import Config
from ledgerkb.core.errors import ConfigError
from ledgerkb.core.ports import ChatModel, Embedder
from ledgerkb.providers.local import LocalEmbedder
from ledgerkb.providers.openai_compat import OpenAICompatChat, OpenAICompatEmbedder

LOCAL_BASE_URLS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104 - matched against a configured URL, never bound to
    "host.docker.internal",
)
"""Endpoints that conventionally need no key — Ollama, vLLM, LM Studio, TEI."""


def _needs_key(base_url: str) -> bool:
    return not any(host in base_url for host in LOCAL_BASE_URLS)


def build_embedder(cfg: Config) -> Embedder:
    """The default is local and needs no credentials."""
    provider = cfg.embeddings.provider
    if provider == "local":
        return LocalEmbedder(
            cfg.embeddings.model,
            dimensions=cfg.embeddings.dimensions,
            batch_size=cfg.embeddings.batch_size,
        )
    if provider == "openai_compatible":
        return OpenAICompatEmbedder(
            cfg.embeddings.model,
            cfg.chat.base_url,
            dimensions=cfg.embeddings.dimensions,
            api_key_env=cfg.chat.api_key_env,
            batch_size=cfg.embeddings.batch_size,
            timeout_s=cfg.chat.timeout_s,
            requires_key=_needs_key(cfg.chat.base_url),
        )
    raise ConfigError(
        f"Unknown embeddings.provider {provider!r}. Known: 'local', "
        "'openai_compatible'. Anything else is supplied in code, through the "
        "Embedder port."
    )


def build_chat(cfg: Config, *, cheap: bool = False) -> ChatModel:
    """``cheap=True`` selects the high-volume model: headers, extraction, grading."""
    if cfg.chat.provider != "openai_compatible":
        raise ConfigError(
            f"Unknown chat.provider {cfg.chat.provider!r}. The base adapter speaks "
            "OpenAI-compatible, which covers roughly 95% of providers including "
            "every local server; anything else is supplied through the ChatModel port."
        )
    tier = cfg.chat.cheap if cheap else cfg.chat
    return OpenAICompatChat(
        tier.model,
        cfg.chat.base_url,
        api_key_env=cfg.chat.api_key_env,
        temperature=tier.temperature,
        timeout_s=cfg.chat.timeout_s,
        requires_key=_needs_key(cfg.chat.base_url),
    )


__all__ = ["build_chat", "build_embedder"]
