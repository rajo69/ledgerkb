"""In-process embedding, so L2 needs no API key and no network.

This is what keeps ``offline.yml`` meaningful past L1. If retrieval could only
be built with a hosted embedder, the offline job would stop proving anything
the moment the first vector was needed, and "runs with zero credentials" would
quietly become "runs, until you want it to work".

``fastembed`` runs ONNX on CPU — no torch, no GPU, no server. The model is
downloaded once and cached; after that it is entirely local.

**On the model.** The build handoff recommended ``BAAI/bge-m3`` via fastembed.
It is not available there — not as a dense model, not sparse, not
late-interaction — so that recommendation could not be implemented as written.
The default is ``mixedbread-ai/mxbai-embed-large-v1``: 1024 dimensions (the
number both design documents already agreed on, so the locked field is
unchanged), Apache-2.0, and the smallest of the permissively-licensed
1024-dimension models fastembed actually serves. ``jinaai/jina-embeddings-v3``
is deliberately excluded from :data:`KNOWN_DIMENSIONS` — it is 1024 dimensions
and otherwise a fine choice, but CC-BY-NC-4.0 is a non-commercial licence and
this project does not ship one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ledgerkb.core.errors import ProviderError

DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-large-v1"

KNOWN_DIMENSIONS: dict[str, int] = {
    "mixedbread-ai/mxbai-embed-large-v1": 1024,   # Apache-2.0
    "BAAI/bge-large-en-v1.5": 1024,               # MIT
    "snowflake/snowflake-arctic-embed-l": 1024,   # Apache-2.0
    "intfloat/multilingual-e5-large": 1024,       # MIT, multilingual
    "BAAI/bge-base-en-v1.5": 768,                 # MIT
    "BAAI/bge-small-en-v1.5": 384,                # MIT
}
"""Permissively-licensed models fastembed serves, with their true widths.

Checked against the config so a mismatch is caught before a single vector is
written, rather than surfacing as a shape error on the first search.
"""


def _import_fastembed() -> Any:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover - exercised by the error path
        raise ProviderError(
            "The local embedder needs fastembed. Install it with: "
            'pip install "ledgerkb[embed]"'
        ) from exc
    return TextEmbedding


class LocalEmbedder:
    """Implements :class:`ledgerkb.core.ports.Embedder`.

    The model loads lazily on first use, so constructing one costs nothing and
    ``lkb doctor`` can report the configuration without downloading weights.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        dimensions: int = 1024,
        batch_size: int = 64,
        cache_dir: str | None = None,
    ) -> None:
        expected = KNOWN_DIMENSIONS.get(model)
        if expected is not None and expected != dimensions:
            raise ProviderError(
                f"{model} produces {expected}-dimensional vectors but the config says "
                f"{dimensions}. Dimensions are locked after the first index build, so "
                "this is caught here rather than after a corpus has been embedded."
            )
        self.name = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            text_embedding = _import_fastembed()
            try:
                self._model = text_embedding(
                    model_name=self.name, cache_dir=self.cache_dir
                )
            except Exception as exc:
                available = ", ".join(sorted(KNOWN_DIMENSIONS))
                raise ProviderError(
                    f"fastembed could not load {self.name!r}: {exc}. "
                    f"Permissively-licensed models known to work: {available}. "
                    "Note the first load downloads weights, so it needs network "
                    "access once even though every later call is offline."
                ) from exc
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            for vector in model.embed(batch):
                values = [float(x) for x in vector]
                if len(values) != self.dimensions:
                    raise ProviderError(
                        f"{self.name} returned {len(values)}-dimensional vectors but "
                        f"the store is configured for {self.dimensions}."
                    )
                out.append(values)
        return out


__all__ = ["DEFAULT_MODEL", "KNOWN_DIMENSIONS", "LocalEmbedder"]
