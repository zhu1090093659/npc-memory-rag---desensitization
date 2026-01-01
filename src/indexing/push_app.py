"""
FastAPI Push Worker for Pub/Sub push mode
Receives HTTP push messages from Google Cloud Pub/Sub

Backpressure mechanism:
- MAX_INFLIGHT_TASKS controls concurrent task processing
- Returns 429 when at capacity, triggering Pub/Sub retry
- Cloud Run autoscaling handles scaling based on request queue
"""

import os
import base64
import json
import asyncio
from typing import Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, HTTPException, Response
from pydantic import BaseModel

from .tasks import IndexTask
from src.memory import Memory, MemoryType, EmbeddingService
from src.es_client import create_es_client
from src.metrics import inc_worker_pulled, inc_worker_processed, observe_bulk_latency

# Concurrency control: limit in-flight tasks to apply backpressure
MAX_INFLIGHT_TASKS = int(os.getenv("MAX_INFLIGHT_TASKS", "4"))
_inflight_semaphore = asyncio.Semaphore(MAX_INFLIGHT_TASKS)

# Thread pool for blocking I/O operations (embedding, ES indexing)
_worker_executor = ThreadPoolExecutor(max_workers=MAX_INFLIGHT_TASKS, thread_name_prefix="worker_")

# Create FastAPI app with OpenAPI documentation
app = FastAPI(
    title="NPC Memory Push Worker",
    description="""
NPC Memory RAG system Push Worker API for processing memory indexing tasks.

This service receives indexing tasks from Google Cloud Pub/Sub push delivery,
generates embeddings using ModelScope Qwen3, and indexes memories to Elasticsearch.

## Endpoints

- **POST /pubsub/push** - Handle Pub/Sub push messages
- **GET /health** - Health check
- **GET /ready** - Readiness check (verifies ES connection)
- **GET /metrics** - Prometheus metrics
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Lazy-initialized components
_es_client = None
_embedder = None


def get_es_client():
    """Get or create ES client (singleton)"""
    global _es_client
    if _es_client is None:
        _es_client = create_es_client()
    return _es_client


def get_embedder():
    """Get or create embedding service (singleton)"""
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService()
    return _embedder


class PubSubMessage(BaseModel):
    """Pub/Sub push message format"""
    message: dict
    subscription: Optional[str] = None


@app.post("/pubsub/push")
async def handle_push(request: Request):
    """
    Handle Pub/Sub push delivery with backpressure.
    Returns 2xx for ack, 429 when overloaded (triggers Pub/Sub retry).
    """
    # Backpressure: reject if at capacity (non-blocking check)
    if _inflight_semaphore.locked():
        raise HTTPException(status_code=429, detail="At capacity, retry later")

    try:
        # Parse request body
        body = await request.json()
        envelope = PubSubMessage(**body)

        # Decode base64 message data
        if "data" not in envelope.message:
            raise HTTPException(status_code=400, detail="Missing message data")

        data = base64.b64decode(envelope.message["data"]).decode("utf-8")
        inc_worker_pulled(1)

        # Parse IndexTask
        try:
            task = IndexTask.from_json(data)
        except Exception as e:
            print(f"[PushWorker] Failed to parse task: {e}")
            inc_worker_processed("error", 1)
            raise HTTPException(status_code=400, detail=f"Invalid task format: {e}")

        # Process with semaphore (limits concurrent processing)
        async with _inflight_semaphore:
            success = await process_single_task(task)

        if success:
            inc_worker_processed("success", 1)
            return {"status": "ok", "task_id": task.task_id}
        else:
            inc_worker_processed("error", 1)
            raise HTTPException(status_code=500, detail="Processing failed")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[PushWorker] Unexpected error: {e}")
        inc_worker_processed("error", 1)
        raise HTTPException(status_code=500, detail=str(e))


def _sync_process_task(task: IndexTask) -> bool:
    """
    Synchronous task processing (runs in thread pool).
    Returns True on success, False on failure.
    """
    import time

    try:
        # Convert to Memory
        memory = Memory(
            id=task.task_id,
            player_id=task.player_id,
            npc_id=task.npc_id,
            memory_type=MemoryType(task.memory_type),
            content=task.content,
            importance=task.importance,
            emotion_tags=task.emotion_tags,
            timestamp=datetime.fromisoformat(task.timestamp),
            game_context=task.game_context
        )

        # Generate embedding (blocking I/O)
        embedder = get_embedder()
        memory.content_vector = embedder.embed(memory.content)

        # Index to ES (blocking I/O)
        es = get_es_client()
        doc = memory.to_es_doc()

        start_time = time.time()
        # Note: routing parameter not supported in Elastic Cloud Serverless mode
        es.index(
            index=os.getenv("INDEX_ALIAS", "npc_memories"),
            id=doc["_id"],
            body={k: v for k, v in doc.items() if not k.startswith("_")}
        )
        observe_bulk_latency(time.time() - start_time)

        return True

    except Exception as e:
        print(f"[PushWorker] Failed to process task {task.task_id}: {e}")
        return False


async def process_single_task(task: IndexTask) -> bool:
    """
    Process a single IndexTask asynchronously.
    Runs blocking I/O in thread pool to avoid blocking event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_worker_executor, _sync_process_task, task)


@app.get("/metrics")
async def metrics():
    """Expose Prometheus metrics"""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response(content="# prometheus_client not installed", media_type="text/plain")


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness check - verifies ES connection"""
    try:
        es = get_es_client()
        if es.ping():
            return {"status": "ready"}
        else:
            raise HTTPException(status_code=503, detail="ES not reachable")
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
