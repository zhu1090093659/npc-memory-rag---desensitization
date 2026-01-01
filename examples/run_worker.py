"""
Run Push Worker for Cloud Run deployment

Usage:
    python examples/run_worker.py

Environment variables:
    - ES_URL: Elasticsearch URL (default: http://localhost:9200)
    - ES_API_KEY: Elastic Cloud API Key (optional, for cloud auth)
    - MODELSCOPE_API_KEY: ModelScope API Key (required for embedding)
    - PORT: HTTP port (default: 8080)
    - MAX_INFLIGHT_TASKS: Max concurrent tasks (default: 4)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def main():
    """Run Push Worker (FastAPI HTTP server for Pub/Sub push delivery)"""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print("=== NPC Memory Push Worker ===")
    print(f"Starting FastAPI server on {host}:{port}")
    print("Endpoints:")
    print("  - POST /pubsub/push  (Pub/Sub push delivery)")
    print("  - GET  /metrics      (Prometheus metrics)")
    print("  - GET  /health       (Health check)")
    print("  - GET  /ready        (Readiness check)")
    print("  - GET  /docs         (Swagger UI)")

    uvicorn.run(
        "src.indexing.push_app:app",
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
