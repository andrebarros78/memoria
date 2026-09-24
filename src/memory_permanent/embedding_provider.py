from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class EmbeddingProviderAdapter(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(slots=True)
class FastEmbedProvider:
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    cache_dir: str | Path | None = None
    threads: int = 2
    identity: str | None = None
    _model: Any = field(init=False, repr=False)
    _dimensions: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from fastembed import TextEmbedding

        model_name = str(self.model_name or "").strip()
        identity = str(self.identity or model_name).strip()
        if not model_name:
            raise ValueError("embedding model_name is required")
        if not identity or len(identity) > 300:
            raise ValueError("embedding identity must contain 1..300 characters")
        self.model_name = model_name
        self.identity = identity
        cache = str(self.cache_dir) if self.cache_dir is not None else None
        self._model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=cache,
            threads=max(1, int(self.threads)),
        )
        probe = next(iter(self._model.embed(["dimension probe"])))
        self._dimensions = len(probe)

    @property
    def model_id(self) -> str:
        return str(self.identity or self.model_name)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        return [[float(x) for x in vector] for vector in self._model.embed(values)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
