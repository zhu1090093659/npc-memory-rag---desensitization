"""
Memory write operations
"""

from typing import List, Optional

from .models import Memory
from src import get_env
from src.indexing import IndexTask


class MemoryWriter:
    """Handles memory write operations"""

    def __init__(
        self,
        es_client,
        embedding_service,
        index_alias: str = None,
        pubsub_publisher=None
    ):
        self.es = es_client
        self.embedder = embedding_service
        self.index_alias = index_alias or get_env("INDEX_ALIAS")
        self.publisher = pubsub_publisher

    def add_memory(self, memory: Memory, async_index: bool = None) -> str:
        """
        Single write (async-only).
        Publishes task to Pub/Sub; synchronous indexing is not supported.
        """
        if not self.publisher:
            raise RuntimeError("Pub/Sub publisher not configured (async-only)")
        return self._publish_index_task(memory)

    def _publish_index_task(self, memory: Memory) -> str:
        """Publish index task to Pub/Sub for async processing"""
        task = IndexTask.create(
            player_id=memory.player_id,
            npc_id=memory.npc_id,
            content=memory.content,
            memory_type=memory.memory_type.value,
            op="index",
            importance=memory.importance,
            emotion_tags=memory.emotion_tags,
            game_context=memory.game_context,
            timestamp=memory.timestamp
        )

        self.publisher.publish(task)
        return task.task_id  # Return task_id as memory_id for tracking

    def bulk_add_memories(self, memories: List[Memory], batch_size: int = 500):
        """
        Bulk write (async-only).
        Queues tasks to Pub/Sub and returns task_id list.
        """
        if not self.publisher:
            raise RuntimeError("Pub/Sub publisher not configured (async-only)")

        tasks = [
            IndexTask.create(
                player_id=m.player_id,
                npc_id=m.npc_id,
                content=m.content,
                memory_type=m.memory_type.value,
                op="index",
                importance=m.importance,
                emotion_tags=m.emotion_tags,
                game_context=m.game_context,
                timestamp=m.timestamp,
            )
            for m in memories
        ]

        # Preserve previous batching behavior, but now as publish batching.
        for i in range(0, len(tasks), batch_size):
            self.publisher.publish_batch(tasks[i:i + batch_size])

        return [t.task_id for t in tasks]
