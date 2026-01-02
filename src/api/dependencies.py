"""
Dependency injection for FastAPI endpoints

Uses singleton pattern for shared resources (ES client, embedder, etc.)
"""

import os
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
