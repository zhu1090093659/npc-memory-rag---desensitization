"""
Example: Run indexing worker in pull or push mode

Usage:
    # Pull mode (default): polls Pub/Sub subscription
    python examples/run_worker.py

    # Push mode: starts FastAPI server for Pub/Sub push delivery
    python examples/run_worker.py --push

Environment variables:
    - WORKER_MODE: "pull" or "push" (default: pull)
    - PUBSUB_PROJECT_ID: GCP project ID (pull mode only)
    - PUBSUB_SUBSCRIPTION: Subscription name (pull mode only)
    - ES_URL: Elasticsearch URL (default: http://localhost:9200)
    - PORT: HTTP port for push mode (default: 8080)
    - METRICS_PORT: Prometheus metrics port for pull mode (default: 8000)
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def run_pull_mode():
    """Run worker in pull mode (polls Pub/Sub subscription)"""
    from src.es_client import create_es_client, initialize_index
    from src.memory import EmbeddingService
    from src.indexing import PubSubSubscriber
    from src.indexing.worker import IndexingWorker
    from src.metrics import start_metrics_server, METRICS_PORT

    print("=== Indexing Worker (Pull Mode) ===")

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

    # Start metrics server
    if start_metrics_server(METRICS_PORT):
        print(f"Metrics available at http://localhost:{METRICS_PORT}/metrics")

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


def run_push_mode():
    """Run worker in push mode (FastAPI HTTP server)"""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print("=== Indexing Worker (Push Mode) ===")
    print(f"Starting FastAPI server on {host}:{port}")
    print("Endpoints:")
    print(f"  - POST /pubsub/push  (Pub/Sub push delivery)")
    print(f"  - GET  /metrics      (Prometheus metrics)")
    print(f"  - GET  /health       (Health check)")
    print(f"  - GET  /ready        (Readiness check)")

    uvicorn.run(
        "src.indexing.push_app:app",
        host=host,
        port=port,
        log_level="info"
    )


def main():
    parser = argparse.ArgumentParser(description="Run NPC Memory indexing worker")
    parser.add_argument(
        "--push",
        action="store_true",
        help="Run in push mode (FastAPI server)"
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Run in pull mode (Pub/Sub polling, default)"
    )
    args = parser.parse_args()

    # Determine mode from args or env
    mode = os.getenv("WORKER_MODE", "pull")
    if args.push:
        mode = "push"
    elif args.pull:
        mode = "pull"

    if mode == "push":
        run_push_mode()
    else:
        run_pull_mode()


if __name__ == "__main__":
    main()
