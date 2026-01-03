"""
NPC Memory RAG Service - Facade layer
Provides backward-compatible interface by composing memory modules
"""

import os
import json
import hashlib
from typing import List, Optional
from datetime import datetime

from src.memory import (
    Memory,
    MemoryType,
    MemoryContext,
    EmbeddingService,
    MemorySearcher,
    MemoryWriter,
    create_index_if_not_exists
)
from src import get_env_int

# Redis cache settings
REDIS_URL = os.getenv("REDIS_URL")
CACHE_TTL_SECONDS = get_env_int("CACHE_TTL_SECONDS")
CACHE_KEY_VERSION = "v1"  # Bump this to invalidate all cache


class RedisCacheAdapter:
    """
    Redis cache adapter for memory query results.
    Serializes Memory objects to JSON (without vectors to save space).
    """

    def __init__(self, redis_url: str = None, ttl: int = None):
        self.ttl = ttl or CACHE_TTL_SECONDS
        self._client = None
        self._init_client(redis_url or REDIS_URL)

    def _init_client(self, redis_url: str):
        """Initialize Redis client"""
        if not redis_url:
            print("[RedisCacheAdapter] No REDIS_URL, cache disabled")
            return

        try:
            import redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
            print(f"[RedisCacheAdapter] Connected to Redis")
        except ImportError:
            print("[RedisCacheAdapter] redis package not installed, cache disabled")
        except Exception as e:
            print(f"[RedisCacheAdapter] Failed to connect: {e}, cache disabled")
            self._client = None

    def get(self, key: str) -> Optional[List[Memory]]:
        """Get cached memories"""
        if not self._client:
            return None

        try:
            versioned_key = f"{CACHE_KEY_VERSION}:{key}"
            data = self._client.get(versioned_key)
            if data:
                return self._deserialize(data)
        except Exception as e:
            print(f"[RedisCacheAdapter] Get error: {e}")
        return None

    def setex(self, key: str, ttl: int, memories: List[Memory]):
        """Set cached memories with TTL"""
        if not self._client:
            return

        try:
            versioned_key = f"{CACHE_KEY_VERSION}:{key}"
            data = self._serialize(memories)
            self._client.setex(versioned_key, ttl or self.ttl, data)
        except Exception as e:
            print(f"[RedisCacheAdapter] Set error: {e}")

    def _serialize(self, memories: List[Memory]) -> str:
        """Serialize memories to JSON (without vectors)"""
        items = []
        for m in memories:
            items.append({
                "id": m.id,
                "player_id": m.player_id,
                "npc_id": m.npc_id,
                "memory_type": m.memory_type.value,
                "content": m.content,
                "emotion_tags": m.emotion_tags,
                "importance": m.importance,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "game_context": m.game_context
            })
        return json.dumps(items, ensure_ascii=False)

    def _deserialize(self, data: str) -> List[Memory]:
        """Deserialize JSON to Memory objects"""
        items = json.loads(data)
        memories = []
        for item in items:
            memories.append(Memory(
                id=item["id"],
                player_id=item["player_id"],
                npc_id=item["npc_id"],
                memory_type=MemoryType(item["memory_type"]),
                content=item["content"],
                emotion_tags=item.get("emotion_tags", []),
                importance=item.get("importance", 0.5),
                timestamp=datetime.fromisoformat(item["timestamp"]) if item.get("timestamp") else None,
                game_context=item.get("game_context")
            ))
        return memories


def create_redis_cache(redis_url: str = None, ttl: int = None) -> Optional[RedisCacheAdapter]:
    """Factory function to create Redis cache (returns None if not available)"""
    adapter = RedisCacheAdapter(redis_url, ttl)
    return adapter if adapter._client else None


class NPCMemoryService:
    """
    NPC Memory Service - Facade/Compatibility layer
    Demonstrates: hybrid search, high-performance queries, data ingestion
    """

    def __init__(self, es_client, embedding_service, cache_client=None, pubsub_publisher=None):
        self.es = es_client
        self.embedder = embedding_service
        self.cache = cache_client
        self.index_alias = "npc_memories"

        # Initialize sub-components
        self.searcher = MemorySearcher(es_client, embedding_service, self.index_alias)
        self.writer = MemoryWriter(es_client, embedding_service, self.index_alias, pubsub_publisher)

    def search_memories(
        self,
        player_id: str,
        npc_id: str,
        query: str,
        top_k: int = 5,
        memory_types: List[MemoryType] = None,
        time_range_days: int = None
    ) -> List[Memory]:
        """
        Hybrid search: BM25 + Vector + RRF fusion
        """
        from src.metrics import inc_cache_hit, inc_cache_miss

        # Check cache
        cache_key = self._cache_key(player_id, npc_id, query)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                inc_cache_hit()
                return cached
            inc_cache_miss()

        # Delegate to searcher
        memories = self.searcher.search_memories(
            player_id, npc_id, query, top_k, memory_types, time_range_days
        )

        # Cache results
        if self.cache:
            self.cache.setex(cache_key, 300, memories)

        return memories

    def add_memory(self, memory: Memory) -> str:
        """Single write (for real-time scenarios)"""
        return self.writer.add_memory(memory)

    def bulk_add_memories(self, memories: List[Memory], batch_size: int = 500):
        """Bulk write - high throughput scenario"""
        return self.writer.bulk_add_memories(memories, batch_size)

    def prepare_context_for_llm(
        self,
        player_id: str,
        npc_id: str,
        current_query: str,
        max_memories: int = 10
    ) -> MemoryContext:
        """
        Prepare memory context for LLM
        Used for RAG: retrieve relevant memories as context
        """
        memories = self.search_memories(player_id, npc_id, current_query, max_memories)

        # Build summary
        if not memories:
            summary = "No previous interactions"
        else:
            summary = self._build_summary(memories)

        # Calculate relationship score
        relationship_score = self._calculate_relationship_score(memories)

        return MemoryContext(
            memories=memories,
            summary=summary,
            total_interactions=len(memories),
            last_interaction=memories[0].timestamp if memories else None,
            relationship_score=relationship_score
        )

    def _build_summary(self, memories: List[Memory]) -> str:
        """Build concise summary of memories"""
        # Count by type
        type_counts = {}
        for m in memories:
            type_counts[m.memory_type.value] = type_counts.get(m.memory_type.value, 0) + 1

        # Extract key emotions
        all_emotions = []
        for m in memories:
            all_emotions.extend(m.emotion_tags)
        top_emotions = list(set(all_emotions))[:3]

        summary_parts = [f"{count}次{mtype}记忆" for mtype, count in type_counts.items()]
        summary = "、".join(summary_parts)

        if top_emotions:
            summary += f"，主要情感：{', '.join(top_emotions)}"

        return summary

    def _calculate_relationship_score(self, memories: List[Memory]) -> float:
        """Calculate relationship score from -1 to 1"""
        if not memories:
            return 0.0

        # Simple scoring based on emotion tags
        positive_emotions = {"感谢", "信任", "友好", "喜悦", "赞赏"}
        negative_emotions = {"愤怒", "失望", "怀疑", "恐惧", "厌恶"}

        positive_count = 0
        negative_count = 0

        for memory in memories:
            for emotion in memory.emotion_tags:
                if emotion in positive_emotions:
                    positive_count += 1
                elif emotion in negative_emotions:
                    negative_count += 1

        total = positive_count + negative_count
        if total == 0:
            return 0.0

        return (positive_count - negative_count) / total

    def _cache_key(self, player_id: str, npc_id: str, query: str) -> str:
        """Generate cache key"""
        return MemorySearcher.cache_key(player_id, npc_id, query)


# Export for backward compatibility
def example_usage():
    """Example usage of memory service"""
    # Initialize (pseudo code)
    # es_client = Elasticsearch(["http://localhost:9200"])
    # embedding_service = EmbeddingService()
    # memory_service = NPCMemoryService(es_client, embedding_service)

    # 1. Store memory
    memory = Memory(
        id="mem_001",
        player_id="player_123",
        npc_id="blacksmith_01",
        memory_type=MemoryType.QUEST,
        content="Player helped blacksmith recover stolen ancestral hammer, blacksmith very grateful",
        emotion_tags=["感谢", "信任"],
        importance=0.8,
        game_context={"location": "village_01", "quest_id": "q_hammer"}
    )
    # memory_service.add_memory(memory)

    # 2. Search memories
    # results = memory_service.search_memories(
    #     player_id="player_123",
    #     npc_id="blacksmith_01",
    #     query="锤子",
    #     top_k=5
    # )

    # 3. Prepare context for LLM
    # context = memory_service.prepare_context_for_llm(
    #     player_id="player_123",
    #     npc_id="blacksmith_01",
    #     current_query="How is the blacksmith doing?",
    #     max_memories=10
    # )

    pass
