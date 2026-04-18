from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import settings
from src.models import SearchDocument

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - import success depends on local environment
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - import success depends on local environment
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        """Fallback Redis error type when redis-py is unavailable."""


class RedisConversationMemory:
    """Persist bounded conversation turns in Redis for follow-up questions."""

    def __init__(
        self,
        redis_client: Any | None = None,
        key_prefix: str | None = None,
        max_turns: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self.key_prefix = key_prefix or settings.redis_key_prefix
        self.max_turns = max_turns or settings.memory_max_turns
        self.ttl_seconds = ttl_seconds or settings.memory_ttl_seconds
        self._fallback_store: dict[str, list[str]] = {}
        self._fallback_expirations: dict[str, float] = {}
        self.client = redis_client if redis_client is not None else self._build_client()

    @property
    def enabled(self) -> bool:
        return True

    @property
    def backend_label(self) -> str:
        if self.client is not None:
            return "redis+local"
        return "local-only"

    def get_history(self, conversation_id: str | None) -> list[dict[str, str]]:
        """Load recent conversation turns from Redis in chronological order."""
        if not conversation_id:
            return []

        key = self._conversation_key(conversation_id)
        fallback_messages = self._fallback_lrange(key)
        try:
            raw_messages = self.client.lrange(key, 0, -1) if self.client is not None else fallback_messages
        except RedisError as exc:
            LOGGER.warning("Redis history load failed for %s: %s", conversation_id, exc)
            raw_messages = fallback_messages

        history: list[dict[str, str]] = []
        for raw_message in raw_messages:
            try:
                decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
                message = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                continue
            if isinstance(message, dict) and isinstance(message.get("role"), str) and isinstance(
                message.get("content"), str
            ):
                history.append({"role": message["role"], "content": message["content"]})
        return history

    def append_turn(
        self,
        conversation_id: str | None,
        question: str,
        answer: str,
        citations: list[SearchDocument] | None = None,
    ) -> None:
        """Append the latest user/assistant pair and trim the transcript."""
        if not conversation_id:
            return

        key = self._conversation_key(conversation_id)
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": answer}
        if citations:
            assistant_entry["citations"] = [self._serialize_citation(citation) for citation in citations]
        entries = (
            json.dumps({"role": "user", "content": question}),
            json.dumps(assistant_entry),
        )
        max_messages = max(self.max_turns * 2, 2)
        self._fallback_rpush(key, *entries)
        self._fallback_ltrim(key, -max_messages, -1)
        if self.ttl_seconds > 0:
            self._fallback_expire(key, self.ttl_seconds)

        if self.client is None:
            return
        try:
            self.client.rpush(key, *entries)
            self.client.ltrim(key, -max_messages, -1)
            if self.ttl_seconds > 0:
                self.client.expire(key, self.ttl_seconds)
        except RedisError as exc:
            LOGGER.warning("Redis history write failed for %s: %s", conversation_id, exc)

    def get_last_citation(self, conversation_id: str | None) -> SearchDocument | None:
        """Return the most recent cited document stored in conversation memory."""
        if not conversation_id:
            return None

        key = self._conversation_key(conversation_id)
        fallback_messages = self._fallback_lrange(key)
        try:
            raw_messages = self.client.lrange(key, 0, -1) if self.client is not None else fallback_messages
        except RedisError as exc:
            LOGGER.warning("Redis citation load failed for %s: %s", conversation_id, exc)
            raw_messages = fallback_messages

        for raw_message in reversed(raw_messages):
            try:
                decoded = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
                message = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                continue

            citations = message.get("citations")
            if not isinstance(citations, list) or not citations:
                continue

            citation = citations[0]
            if not isinstance(citation, dict):
                continue

            source_type = citation.get("source_type")
            title = citation.get("title")
            url = citation.get("url")
            content = citation.get("content", "")
            metadata = citation.get("metadata") or {}
            if (
                isinstance(source_type, str)
                and isinstance(title, str)
                and isinstance(url, str)
                and isinstance(content, str)
                and isinstance(metadata, dict)
            ):
                return SearchDocument(
                    source_type=source_type,
                    title=title,
                    url=url,
                    content=content,
                    metadata=metadata,
                )
        return None

    def _conversation_key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}:memory:{conversation_id}"

    def _fallback_lrange(self, key: str) -> list[str]:
        self._fallback_cleanup(key)
        return list(self._fallback_store.get(key, []))

    def _fallback_rpush(self, key: str, *values: str) -> None:
        self._fallback_cleanup(key)
        self._fallback_store.setdefault(key, []).extend(values)

    def _fallback_ltrim(self, key: str, start: int, end: int) -> None:
        values = self._fallback_store.get(key, [])
        length = len(values)
        normalized_start = start if start >= 0 else max(length + start, 0)
        normalized_end = end if end >= 0 else length + end
        self._fallback_store[key] = values[normalized_start : normalized_end + 1]

    def _fallback_expire(self, key: str, ttl_seconds: int) -> None:
        self._fallback_expirations[key] = time.time() + ttl_seconds

    def _fallback_cleanup(self, key: str) -> None:
        expires_at = self._fallback_expirations.get(key)
        if expires_at is not None and expires_at <= time.time():
            self._fallback_store.pop(key, None)
            self._fallback_expirations.pop(key, None)

    @staticmethod
    def _serialize_citation(citation: SearchDocument) -> dict[str, Any]:
        return {
            "source_type": citation.source_type,
            "title": citation.title,
            "url": citation.url,
            "content": citation.content[:500],
            "metadata": citation.metadata,
        }

    @staticmethod
    def _build_client() -> Any | None:
        if not settings.redis_url or Redis is None:
            return None

        try:
            client = Redis.from_url(
                settings.redis_url,
                decode_responses=False,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            return client
        except RedisError as exc:
            LOGGER.warning("Redis memory disabled because connection failed: %s", exc)
            return None
