"""
Dependency injection for FastAPI endpoints

Uses singleton pattern for shared resources (ES client, embedder, etc.)
"""

import os
import json
from functools import lru_cache
from typing import Optional

from src.es_client import create_es_client
from src.memory import EmbeddingService
from src.memory_service import NPCMemoryService, create_redis_cache
from src.indexing import PubSubPublisher


# Lazy-initialized singletons
_es_client = None
_embedder = None
_publisher = None
_memory_service = None
_reply_store = None


class RedisReplyStore:
    """
    Request-reply store backed by Redis lists.

    Worker writes reply via LPUSH; API waits via BRPOP to avoid busy polling.
    """

    def __init__(self, redis_url: str, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._client = None
        self._init_client(redis_url)

    def _init_client(self, redis_url: str):
        """Initialize Redis client"""
        try:
            import redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
        except ImportError:
            print("[RedisReplyStore] redis package not installed, reply-store disabled")
            self._client = None
        except Exception as e:
            print(f"[RedisReplyStore] Failed to connect: {e}, reply-store disabled")
            self._client = None

    @staticmethod
    def _key(task_id: str) -> str:
        return f"reply:{task_id}"

    def wait(self, task_id: str, timeout_seconds: int) -> Optional[dict]:
        """
        Blocking wait for reply payload.
        Returns parsed JSON dict, or None on timeout.
        """
        if not self._client:
            return None

        item = self._client.brpop(self._key(task_id), timeout=timeout_seconds)
        if not item:
            return None

        _, data = item
        try:
            return json.loads(data)
        except Exception:
            return {"status": "error", "task_id": task_id, "error": "Invalid reply payload"}


def get_es_client():
    """Get or create ES client (singleton)"""
    global _es_client
    if _es_client is None:
        _es_client = create_es_client()
    return _es_client


def get_embedder():
    """Get or create embedding service (singleton)"""
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService()
    return _embedder


def get_publisher() -> Optional[PubSubPublisher]:
    """Get or create Pub/Sub publisher (singleton)"""
    global _publisher
    if _publisher is None:
        # Only create publisher if async indexing is enabled
        if os.getenv("INDEX_ASYNC_ENABLED", "false").lower() == "true":
            try:
                _publisher = PubSubPublisher()
            except Exception as e:
                print(f"[Dependencies] Failed to create PubSubPublisher: {e}")
                _publisher = None
    return _publisher


def get_reply_store() -> Optional[RedisReplyStore]:
    """Get or create Redis reply-store (singleton)"""
    global _reply_store
    if _reply_store is not None:
        return _reply_store

    redis_url = os.getenv("REDIS_URL")
    ttl_seconds = int(os.getenv("REPLY_TTL_SECONDS", "60"))
    if not redis_url:
        print("[Dependencies] REDIS_URL not set, reply-store disabled")
        _reply_store = None
        return None

    store = RedisReplyStore(redis_url=redis_url, ttl_seconds=ttl_seconds)
    _reply_store = store if store._client else None
    return _reply_store


def get_memory_service() -> NPCMemoryService:
    """
    Get or create NPCMemoryService (singleton)

    Composes: ES client, embedder, cache, and optional publisher
    """
    global _memory_service
    if _memory_service is None:
        es = get_es_client()
        embedder = get_embedder()
        cache = create_redis_cache()
        publisher = get_publisher()
        _memory_service = NPCMemoryService(es, embedder, cache, publisher)
    return _memory_service
