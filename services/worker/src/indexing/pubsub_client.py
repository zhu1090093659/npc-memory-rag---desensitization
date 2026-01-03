"""
Pub/Sub client wrapper for task publishing and subscription
"""

from typing import List, Optional
import os
from google.cloud import pubsub_v1

from .tasks import IndexTask
from src import get_env


class PubSubPublisher:
    """Publishes index tasks to Pub/Sub topic"""

    def __init__(self, project_id: str = None, topic_name: str = None):
        self.project_id = project_id or os.getenv("PUBSUB_PROJECT_ID")
        self.topic_name = topic_name or os.getenv("PUBSUB_TOPIC")

        if not self.project_id:
            raise ValueError("PUBSUB_PROJECT_ID not set")
        if not self.topic_name:
            raise ValueError("PUBSUB_TOPIC not set")

        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

    def publish(self, task: IndexTask) -> str:
        """
        Publish single task to topic
        Returns: message ID
        """
        data = task.to_json().encode("utf-8")
        # Add attributes to help trace producers and message schema.
        attrs = {
            "producer": get_env("PUBSUB_PRODUCER"),
            "schema": "IndexTask.v1",
            "op": str(getattr(task, "op", "") or ""),
        }
        future = self.publisher.publish(self.topic_path, data, **attrs)
        message_id = future.result()  # Block until published
        return message_id

    def publish_batch(self, tasks: List[IndexTask]) -> List[str]:
        """
        Publish multiple tasks
        Returns: list of message IDs
        """
        futures = []
        for task in tasks:
            data = task.to_json().encode("utf-8")
            attrs = {
                "producer": get_env("PUBSUB_PRODUCER"),
                "schema": "IndexTask.v1",
                "op": str(getattr(task, "op", "") or ""),
            }
            future = self.publisher.publish(self.topic_path, data, **attrs)
            futures.append(future)

        # Wait for all to complete
        message_ids = [f.result() for f in futures]
        return message_ids
