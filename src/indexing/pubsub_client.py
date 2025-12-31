"""
Pub/Sub client wrapper for task publishing and subscription
"""

from typing import List, Optional
import os
from google.cloud import pubsub_v1
from google.api_core import retry

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


class PubSubSubscriber:
    """Pulls and processes index tasks from subscription"""

    def __init__(self, project_id: str = None, subscription_name: str = None):
        self.project_id = project_id or os.getenv("PUBSUB_PROJECT_ID")
        self.subscription_name = subscription_name or os.getenv(
            "PUBSUB_SUBSCRIPTION", "index-tasks-sub"
        )

        if not self.project_id:
            raise ValueError("PUBSUB_PROJECT_ID not set")

        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            self.project_id, self.subscription_name
        )

    def pull(self, max_messages: int = 10, return_immediately: bool = False) -> List[tuple]:
        """
        Pull messages from subscription
        Returns: list of (IndexTask, ack_id) tuples
        """
        request = {
            "subscription": self.subscription_path,
            "max_messages": max_messages,
            "return_immediately": return_immediately,
        }

        response = self.subscriber.pull(request=request, retry=retry.Retry(deadline=30))

        results = []
        for received_message in response.received_messages:
            data = received_message.message.data.decode("utf-8")
            try:
                task = IndexTask.from_json(data)
                results.append((task, received_message.ack_id))
            except Exception as e:
                print(f"Failed to parse message: {e}")
                # Still append with None task to allow nack
                results.append((None, received_message.ack_id))

        return results

    def ack(self, ack_ids: List[str]):
        """Acknowledge processed messages"""
        if not ack_ids:
            return

        request = {
            "subscription": self.subscription_path,
            "ack_ids": ack_ids,
        }
        self.subscriber.acknowledge(request=request)

    def nack(self, ack_ids: List[str]):
        """
        Negative acknowledge - put messages back for reprocessing
        (modify ack deadline to 0)
        """
        if not ack_ids:
            return

        request = {
            "subscription": self.subscription_path,
            "ack_ids": ack_ids,
            "ack_deadline_seconds": 0,
        }
        self.subscriber.modify_ack_deadline(request=request)
