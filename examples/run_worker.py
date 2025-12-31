"""
Example: Run indexing worker to consume tasks from Pub/Sub

Usage:
    python examples/run_worker.py

Environment variables:
    - PUBSUB_PROJECT_ID: GCP project ID
    - PUBSUB_SUBSCRIPTION: Subscription name (default: index-tasks-sub)
    - ES_URL: Elasticsearch URL (default: http://localhost:9200)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.es_client import create_es_client, initialize_index
from src.memory import EmbeddingService
from src.indexing import PubSubSubscriber
from src.indexing.worker import IndexingWorker


def main():
    """Run indexing worker"""
    print("=== Indexing Worker ===")

    # Initialize ES client
    print("Connecting to Elasticsearch...")
    es = create_es_client()
    print(f"Connected to ES cluster: {es.info()['cluster_name']}")

    # Initialize index if needed
    initialize_index(es)

    # Initialize embedding service
    print("Initializing embedding service...")
    embedder = EmbeddingService()

    # Initialize Pub/Sub subscriber
    print("Connecting to Pub/Sub...")
    subscriber = PubSubSubscriber()

    # Create worker
    worker = IndexingWorker(
        es_client=es,
        embedding_service=embedder,
        subscriber=subscriber
    )

    # Run worker loop
    print("\nStarting worker loop (Ctrl+C to stop)...")
    try:
        worker.run_loop(max_messages=10, batch_size=50)
    except KeyboardInterrupt:
        print("\nWorker stopped by user")


if __name__ == "__main__":
    main()
