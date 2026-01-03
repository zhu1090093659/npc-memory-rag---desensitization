"""
Memory write operations
"""

import os
from typing import List, Optional

from elasticsearch.helpers import bulk, BulkIndexError

from .models import Memory

# Elastic Cloud Serverless does not support routing parameter
ES_ROUTING_ENABLED = os.getenv("ES_ROUTING_ENABLED", "false").lower() == "true"


class MemoryWriter:
    """Handles memory write operations"""

    def __init__(
        self,
        es_client,
        embedding_service,
        index_alias: str = "npc_memories",
        pubsub_publisher=None
    ):
        self.es = es_client
        self.embedder = embedding_service
        self.index_alias = index_alias
        self.publisher = pubsub_publisher
        self.async_enabled = os.getenv("INDEX_ASYNC_ENABLED", "false").lower() == "true"

    def add_memory(self, memory: Memory, async_index: bool = None) -> str:
        """
        Single write (for real-time scenarios)
        If async_index is enabled, publishes task to Pub/Sub instead of direct indexing
        """
        # Check if should use async indexing
        use_async = async_index if async_index is not None else self.async_enabled

        if use_async and self.publisher:
            return self._publish_index_task(memory)
        else:
            return self._sync_index(memory)

    def _sync_index(self, memory: Memory) -> str:
        """Synchronous direct indexing"""
        doc = memory.to_es_doc()

        # Generate vector if not exists
        if not memory.content_vector:
            doc["content_vector"] = self.embedder.embed(memory.content)

        # Build index params (routing not supported in Serverless mode)
        index_params = {
            "index": self.index_alias,
            "id": doc["_id"],
            "body": {k: v for k, v in doc.items() if not k.startswith("_")}
        }
        if ES_ROUTING_ENABLED:
            index_params["routing"] = doc["_routing"]

        response = self.es.index(**index_params)
        return response["_id"]

    def _publish_index_task(self, memory: Memory) -> str:
        """Publish index task to Pub/Sub for async processing"""
        from src.indexing import IndexTask

        task = IndexTask.create(
            player_id=memory.player_id,
            npc_id=memory.npc_id,
            content=memory.content,
            memory_type=memory.memory_type.value,
            importance=memory.importance,
            emotion_tags=memory.emotion_tags,
            game_context=memory.game_context,
            timestamp=memory.timestamp
        )

        message_id = self.publisher.publish(task)
        return task.task_id  # Return task_id as memory_id for tracking

    def bulk_add_memories(self, memories: List[Memory], batch_size: int = 500):
        """
        Bulk write - high throughput scenario
        Demonstrates: bulk API, batch embedding, error handling
        """
        # Batch generate embeddings
        contents = [m.content for m in memories if not m.content_vector]
        if contents:
            vectors = self.embedder.batch_embed(contents)
            vector_idx = 0
            for m in memories:
                if not m.content_vector:
                    m.content_vector = vectors[vector_idx]
                    vector_idx += 1

        # Build bulk operations (routing not supported in Serverless mode)
        actions = []
        for memory in memories:
            doc = memory.to_es_doc()
            action = {
                "_index": self.index_alias,
                "_id": doc["_id"],
                "_source": {k: v for k, v in doc.items() if not k.startswith("_")}
            }
            if ES_ROUTING_ENABLED:
                action["_routing"] = doc["_routing"]
            actions.append(action)

        # Execute in batches
        success_count = 0
        error_count = 0

        for i in range(0, len(actions), batch_size):
            batch = actions[i:i + batch_size]
            try:
                success, failed = bulk(
                    self.es,
                    batch,
                    raise_on_error=False,
                    refresh=False  # Don't refresh immediately for better throughput
                )
                success_count += success
                error_count += len(failed)
            except BulkIndexError as e:
                error_count += len(e.errors)
                # Log errors
                for error in e.errors:
                    print(f"Bulk error: {error}")

        return {"success": success_count, "errors": error_count}
