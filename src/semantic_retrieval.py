from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import numpy as np

from config import settings
from src.models import SearchDocument

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional import in runtime
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional import in runtime
    SentenceTransformer = None  # type: ignore[assignment]


class TextEmbedder(Protocol):
    """Minimal embedder contract used by the semantic retriever."""

    model_name: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode input texts into a 2D float array."""


class SentenceTransformerEmbedder:
    """Thin wrapper around a sentence-transformers model."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.as400_embedding_model
        self._model = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        model = self._load_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def _load_model(self):
        if self._model is not None:
            return self._model
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not installed. Install dependencies from requirements.txt."
            )
        try:
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
        except Exception:
            self._model = SentenceTransformer(self.model_name)
        return self._model


class SemanticDocumentIndex:
    """Persistent embedding index for local documents."""

    def __init__(
        self,
        index_path: str | Path | None = None,
        embedder: TextEmbedder | None = None,
    ) -> None:
        self.index_path = Path(index_path or settings.as400_index_path)
        self.embedder = embedder or SentenceTransformerEmbedder()
        self._embeddings: np.ndarray | None = None
        self._signature: str = ""

    def search(
        self,
        query: str,
        documents: list[SearchDocument],
        limit: int,
    ) -> list[tuple[SearchDocument, float]]:
        """Return documents ranked by cosine similarity against the transformer embedding."""
        if not documents:
            return []

        self._ensure_index(documents)
        assert self._embeddings is not None

        query_embedding = self.embedder.encode([query])
        if query_embedding.size == 0:
            return []

        scores = self._embeddings @ query_embedding[0]
        ranked_indices = np.argsort(scores)[::-1][:limit]
        return [(documents[index], float(scores[index])) for index in ranked_indices]

    def _ensure_index(self, documents: list[SearchDocument]) -> None:
        signature = self._signature_for(documents)
        if self._embeddings is not None and self._signature == signature:
            return

        cached = self._load_cached(signature)
        if cached is not None:
            self._embeddings = cached
            self._signature = signature
            return

        texts = [self._document_text(document) for document in documents]
        embeddings = self.embedder.encode(texts)
        self._embeddings = self._normalize_rows(embeddings)
        self._signature = signature
        self._save_cached(self._embeddings, signature)

    def _load_cached(self, signature: str) -> np.ndarray | None:
        if not self.index_path.exists():
            return None
        try:
            payload = np.load(self.index_path, allow_pickle=False)
            cached_signature = str(payload["signature"][0])
            if cached_signature != signature:
                return None
            return np.asarray(payload["embeddings"], dtype=np.float32)
        except Exception as exc:  # pragma: no cover - corrupted cache fallback
            LOGGER.warning("Failed to load semantic index cache from %s: %s", self.index_path, exc)
            return None

    def _save_cached(self, embeddings: np.ndarray, signature: str) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self.index_path,
            embeddings=embeddings.astype(np.float32),
            signature=np.asarray([signature]),
        )

    def _signature_for(self, documents: list[SearchDocument]) -> str:
        payload = {
            "model": self.embedder.model_name,
            "documents": [asdict(document) for document in documents],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _document_text(document: SearchDocument) -> str:
        metadata = " ".join(
            f"{key}={value}" for key, value in sorted(document.metadata.items()) if isinstance(value, (str, int, float))
        )
        return f"{document.title}\n{metadata}\n{document.content}"

    @staticmethod
    def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            return np.asarray(matrix, dtype=np.float32)
        matrix = np.asarray(matrix, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms
