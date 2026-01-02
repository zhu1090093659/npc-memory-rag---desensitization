"""
Pub/Sub client wrapper for task publishing and subscription
"""

from typing import List, Optional
import os
from google.cloud import pubsub_v1

from .tasks import IndexTask


class PubSubPublisher:
    """Publishes index tasks to Pub/Sub topic"""

    def __init__(self, project_id: str = None, topic_name: str = None):
        self.project_id = project_id or os.getenv("PUBSUB_PROJECT_ID")
        self.topic_name = topic_name or os.getenv("PUBSUB_TOPIC", "index-tasks")

        if not self.project_id:
            raise ValueError("PUBSUB_PROJECT_ID not set")

        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

    def publish(self, task: IndexTask) -> str:
        """
        Publish single task to topic
        Returns: message ID
        """
        data = task.to_json().encode("utf-8")
        future = self.publisher.publish(self.topic_path, data)
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
            future = self.publisher.publish(self.topic_path, data)
            futures.append(future)

        # Wait for all to complete
        message_ids = [f.result() for f in futures]
        return message_ids
