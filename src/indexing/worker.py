"""
Indexing worker: pull tasks from Pub/Sub and process them
"""

from typing import List, Optional
from datetime import datetime
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk, BulkIndexError

from .pubsub_client import PubSubSubscriber
from .tasks import IndexTask
from src.memory import Memory, MemoryType, EmbeddingService


class IndexingWorker:
    """
    Pulls index tasks from Pub/Sub subscription, processes them with:
    - Batch embedding
    - Bulk ES indexing
    - Idempotency via task_id
    """

    def __init__(
        self,
        es_client: Elasticsearch,
        embedding_service: EmbeddingService,
        subscriber: PubSubSubscriber,
        index_alias: str = "npc_memories"
    ):
        self.es = es_client
        self.embedder = embedding_service
        self.subscriber = subscriber
        self.index_alias = index_alias

    def run_once(self, max_messages: int = 10, batch_size: int = 50) -> dict:
        """
        Pull and process one batch of messages
        Returns: processing stats
        """
        # Pull messages
        messages = self.subscriber.pull(max_messages=max_messages)

        if not messages:
            return {"pulled": 0, "processed": 0, "errors": 0}

        # Separate valid tasks from parse errors
        valid_tasks = []
        valid_ack_ids = []
        error_ack_ids = []

        for task, ack_id in messages:
            if task is None:
                error_ack_ids.append(ack_id)
            else:
                valid_tasks.append(task)
                valid_ack_ids.append(ack_id)

        # Process valid tasks
        success_count, error_count = self._process_tasks(valid_tasks, batch_size)

        # Ack successfully processed messages
        # (simple strategy: ack all valid tasks; for production add partial ack logic)
        if success_count > 0 and valid_ack_ids:
            self.subscriber.ack(valid_ack_ids)

        # Nack parse errors (will retry or go to dead letter)
        if error_ack_ids:
            self.subscriber.nack(error_ack_ids)

        return {
            "pulled": len(messages),
            "processed": success_count,
            "errors": error_count + len(error_ack_ids)
        }

    def run_loop(self, max_messages: int = 10, batch_size: int = 50):
        """
        Continuous processing loop
        (for production use, add graceful shutdown signal handling)
        """
        print(f"Worker starting. Polling subscription with max_messages={max_messages}")

        while True:
            try:
                stats = self.run_once(max_messages, batch_size)
                if stats["pulled"] > 0:
                    print(f"Batch complete: {stats}")
                else:
                    # No messages, brief sleep
                    import time
                    time.sleep(2)
            except KeyboardInterrupt:
                print("Worker stopped by user")
                break
            except Exception as e:
                print(f"Worker error: {e}")
                import time
                time.sleep(5)

    def _process_tasks(self, tasks: List[IndexTask], batch_size: int) -> tuple:
        """
        Process tasks: batch embed + bulk index
        Returns: (success_count, error_count)
        """
        if not tasks:
            return 0, 0

        # Convert tasks to Memory objects
        memories = []
        for task in tasks:
            try:
                memory = Memory(
                    id=task.task_id,  # Use task_id as memory ID for idempotency
                    player_id=task.player_id,
                    npc_id=task.npc_id,
                    memory_type=MemoryType(task.memory_type),
                    content=task.content,
                    importance=task.importance,
                    emotion_tags=task.emotion_tags,
                    timestamp=datetime.fromisoformat(task.timestamp),
                    game_context=task.game_context
                )
                memories.append(memory)
            except Exception as e:
                print(f"Failed to convert task {task.task_id}: {e}")

        if not memories:
            return 0, len(tasks)

        # Batch embed
        contents = [m.content for m in memories]
        try:
            vectors = self.embedder.batch_embed(contents)
            for i, memory in enumerate(memories):
                memory.content_vector = vectors[i]
        except Exception as e:
            print(f"Batch embedding failed: {e}")
            return 0, len(memories)

        # Bulk index to ES
        success_count, error_count = self._bulk_index(memories, batch_size)

        return success_count, error_count

    def _bulk_index(self, memories: List[Memory], batch_size: int) -> tuple:
        """
        Bulk index memories to ES with idempotency
        Returns: (success_count, error_count)
        """
        actions = []
        for memory in memories:
            doc = memory.to_es_doc()
            actions.append({
                "_index": self.index_alias,
                "_id": doc["_id"],  # task_id as _id for idempotency
                "_routing": doc["_routing"],
                "_source": {k: v for k, v in doc.items() if not k.startswith("_")},
                "_op_type": "index"  # Overwrite if exists (idempotent)
            })

        success_count = 0
        error_count = 0

        for i in range(0, len(actions), batch_size):
            batch = actions[i:i + batch_size]
            try:
                success, failed = bulk(
                    self.es,
                    batch,
                    raise_on_error=False,
                    refresh=False
                )
                success_count += success
                error_count += len(failed)
            except BulkIndexError as e:
                error_count += len(e.errors)
                for error in e.errors:
                    print(f"Bulk error: {error}")

        return success_count, error_count
