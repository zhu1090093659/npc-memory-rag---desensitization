"""
Example: Publish index tasks to Pub/Sub

Usage:
    python examples/publish_task.py

Environment variables:
    - PUBSUB_PROJECT_ID: GCP project ID
    - PUBSUB_TOPIC: Topic name (default: index-tasks)
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.indexing import IndexTask, PubSubPublisher


def main():
    """Publish sample index tasks"""
    print("=== Publishing Index Tasks ===")

    # Initialize publisher
    publisher = PubSubPublisher()
    print(f"Publishing to topic: {publisher.topic_path}")

    # Create sample tasks
    tasks = [
        IndexTask.create(
            player_id="player_001",
            npc_id="blacksmith_01",
            content="玩家帮助铁匠找回了被盗的祖传锤子",
            memory_type="quest",
            importance=0.8,
            emotion_tags=["感谢", "信任"],
            game_context={"location": "village_01", "quest_id": "q_hammer"}
        ),
        IndexTask.create(
            player_id="player_001",
            npc_id="blacksmith_01",
            content="玩家再次拜访铁匠，购买了一把精良的剑",
            memory_type="trade",
            importance=0.5,
            emotion_tags=["友好"],
            game_context={"location": "village_01", "item_id": "sword_iron_01"}
        ),
        IndexTask.create(
            player_id="player_002",
            npc_id="merchant_01",
            content="玩家向商人询问关于远方城市的消息",
            memory_type="dialogue",
            importance=0.3,
            emotion_tags=[],
            game_context={"location": "marketplace"}
        ),
    ]

    # Publish tasks
    print(f"\nPublishing {len(tasks)} tasks...")
    message_ids = publisher.publish_batch(tasks)

    print("\nPublished tasks:")
    for task, msg_id in zip(tasks, message_ids):
        print(f"  - Task {task.task_id}: message_id={msg_id}")
        print(f"    Content: {task.content[:50]}...")

    print(f"\nTotal published: {len(message_ids)} tasks")


if __name__ == "__main__":
    main()
