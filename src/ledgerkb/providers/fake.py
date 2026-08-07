"""Deterministic fake providers.

Every test defaults to these: zero API calls, zero cost, zero flake. Real
providers are exercised only by ``@pytest.mark.live`` tests in the nightly
drift workflow, whose job is to catch silent provider behaviour changes.

Determinism comes from hashing the input, so the same prompt always yields the
same output across processes, machines and Python versions — unlike ``hash()``,
which is salted per process.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from ledgerkb.core.errors import ProviderError
from ledgerkb.core.ports import Capabilities

T = TypeVar("T", bound=BaseModel)


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


class FakeChatModel:
    """Implements :class:`ledgerkb.core.ports.ChatModel`.

    ``structured`` fills a schema with type-appropriate placeholder values
    rather than parsing anything, so tests exercise plumbing and validators
    without pretending a model was involved.
    """

    def __init__(
        self, name: str = "fake/deterministic", *, responses: dict[str, str] | None = None
    ) -> None:
        self.name = name
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> str:
        self._record(messages, kw)
        prompt = self._flatten(messages)
        for needle, canned in self.responses.items():
            if needle in prompt:
                return canned
        return f"fake-completion:{_seed(prompt):016x}"

    def structured(self, messages: list[dict[str, Any]], schema: type[T], **kw: Any) -> T:
        self._record(messages, kw)
        prompt = self._flatten(messages)
        for needle, canned in self.responses.items():
            if needle in prompt:
                return schema.model_validate_json(canned)
        try:
            return schema.model_validate(_fill(schema, _seed(prompt)))
        except ValueError as exc:
            raise ProviderError(
                f"FakeChatModel cannot synthesise a valid {schema.__name__}: {exc}. "
                "Supply a canned response for this schema."
            ) from exc

    def capabilities(self) -> Capabilities:
        return Capabilities(
            structured_output=True,
            tools=False,
            max_input_tokens=128_000,
            max_output_tokens=8_192,
            cost_per_1m_input_usd=0.0,
            cost_per_1m_output_usd=0.0,
        )

    def _record(self, messages: list[dict[str, Any]], kw: dict[str, Any]) -> None:
        # Extraction calls carry zero tools — the architectural anti-injection
        # control. The fake asserts it so a regression fails in CI, not in prod.
        if kw.get("tools"):
            raise ProviderError(
                "tools were passed to a chat call; extraction calls carry zero tools by design"
            )
        self.calls.append({"messages": messages, "kw": kw})

    @staticmethod
    def _flatten(messages: list[dict[str, Any]]) -> str:
        return "\n".join(str(m.get("content", "")) for m in messages)


def _fill(schema: type[BaseModel], seed: int) -> dict[str, Any]:
    """Synthesise a minimal valid payload for a Pydantic schema."""
    out: dict[str, Any] = {}
    for name, info in schema.model_fields.items():
        if not info.is_required():
            continue
        ann = info.annotation
        if ann is str or ann is None:
            out[name] = f"fake-{name}-{seed % 10_000}"
        elif ann is int:
            out[name] = seed % 100
        elif ann is float:
            out[name] = (seed % 100) / 100
        elif ann is bool:
            out[name] = bool(seed % 2)
        elif isinstance(ann, type) and issubclass(ann, BaseModel):
            out[name] = _fill(ann, seed)
        else:
            out[name] = f"fake-{name}"
    return out


class FakeEmbedder:
    """Implements :class:`ledgerkb.core.ports.Embedder`.

    Vectors are hash-derived and L2-normalised. Identical text always embeds
    identically and different text almost never collides, which is all the
    retrieval tests need.
    """

    def __init__(self, name: str = "fake/embedder", dimensions: int = 1024) -> None:
        self.name = name
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        digest = hashlib.sha512(text.encode("utf-8")).digest()
        vals: list[float] = []
        counter = 0
        while len(vals) < self.dimensions:
            block = hashlib.sha512(digest + counter.to_bytes(4, "big")).digest()
            vals.extend((b - 127.5) / 127.5 for b in block)
            counter += 1
        vals = vals[: self.dimensions]
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]


class FakeReranker:
    """Implements :class:`ledgerkb.core.ports.Reranker`. Scores by token overlap."""

    def rerank(self, query: str, docs: Sequence[str], top_k: int) -> list[tuple[int, float]]:
        q = set(query.lower().split())
        scored = [
            (i, len(q & set(d.lower().split())) / (len(q) or 1)) for i, d in enumerate(docs)
        ]
        scored.sort(key=lambda p: (-p[1], p[0]))
        return scored[:top_k]


def canned(payload: BaseModel) -> str:
    """Serialise a model for use as a ``responses`` value."""
    return json.dumps(payload.model_dump(mode="json"))


__all__ = ["FakeChatModel", "FakeEmbedder", "FakeReranker", "canned"]
