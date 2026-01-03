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
import hashlib
from typing import Optional, Any, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, HTTPException, Response
from pydantic import BaseModel

from .tasks import IndexTask
from src.memory import Memory, MemoryType, EmbeddingService
from src.memory.search import MemorySearcher
from src.es_client import create_es_client
from src.metrics import inc_worker_pulled, inc_worker_processed, observe_bulk_latency
from src import get_env, get_env_int

# Concurrency control: limit in-flight tasks to apply backpressure
MAX_INFLIGHT_TASKS = get_env_int("MAX_INFLIGHT_TASKS")
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
_redis_client = None

# Reply channel configuration (request-reply via Redis)
REPLY_TTL_SECONDS = get_env_int("REPLY_TTL_SECONDS")


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


def get_redis_client():
    """Get or create Redis client (singleton)"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL not set (required for request-reply)")

    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()
        return _redis_client
    except ImportError as e:
        raise RuntimeError("redis package not installed") from e
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Redis: {e}") from e


def _reply_key(task_id: str) -> str:
    return f"reply:{task_id}"


def write_reply(task_id: str, payload: dict):
    """
    Write reply payload to Redis so the API service can BRPOP it.
    Uses a list to allow BRPOP blocking wait.
    """
    client = get_redis_client()
    key = _reply_key(task_id)
    data = json.dumps(payload, ensure_ascii=False)
    client.lpush(key, data)
    client.expire(key, REPLY_TTL_SECONDS)


class PubSubMessage(BaseModel):
    """Pub/Sub push message format"""
    message: dict
    subscription: Optional[str] = None


def _safe_preview(text: str, limit: int = 200) -> str:
    """Return a safe preview for logs (single line, limited length)."""
    if text is None:
        return ""
    t = text.replace("\r", " ").replace("\n", " ").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "..."


def _task_from_payload(data_str: str) -> IndexTask:
    """
    Parse IndexTask from payload string.
    Primary format: JSON.
    Compatibility format: python dict literal (single quotes) produced by str(dict).
    """
    try:
        return IndexTask.from_json(data_str)
    except Exception:
        # Compatibility: try python literal dict -> json
        import ast

        obj = ast.literal_eval(data_str)
        if not isinstance(obj, dict):
            raise ValueError("Payload is not a dict")
        return IndexTask(**obj)


def _envelope_meta(envelope: PubSubMessage) -> Tuple[str, str, Any]:
    """Extract useful metadata for debugging."""
    msg = envelope.message or {}
    message_id = str(msg.get("messageId") or msg.get("message_id") or "")
    publish_time = str(msg.get("publishTime") or msg.get("publish_time") or "")
    attributes = msg.get("attributes") or {}
    return message_id, publish_time, attributes


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
        message_id, publish_time, attributes = _envelope_meta(envelope)

        # Decode base64 message data
        if "data" not in envelope.message:
            # Ack and drop: avoid retry storm for malformed messages.
            print(f"[PushWorker] Drop malformed message (missing data). message_id={message_id} publish_time={publish_time} attributes={attributes}")
            inc_worker_processed("dropped", 1)
            return Response(status_code=204)

        data = base64.b64decode(envelope.message["data"]).decode("utf-8", errors="replace")
        inc_worker_pulled(1)

        # Parse IndexTask
        try:
            task = _task_from_payload(data)
        except Exception as e:
            digest = hashlib.sha256(data.encode("utf-8", errors="ignore")).hexdigest()[:12]
            preview = _safe_preview(data)
            print(
                "[PushWorker] Drop invalid task payload. "
                f"message_id={message_id} publish_time={publish_time} "
                f"attributes={attributes} sha256_12={digest} preview={preview} error={e}"
            )
            # Ack and drop: this message is not processable; retrying wastes capacity.
            inc_worker_processed("dropped", 1)
            return Response(status_code=204)

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
        op = (task.op or "index").lower()

        if op == "search":
            es = get_es_client()
            embedder = get_embedder()
            index_alias = get_env("INDEX_ALIAS")
            searcher = MemorySearcher(es, embedder, index_alias=index_alias)

            types = None
            if task.memory_types:
                try:
                    types = [MemoryType(t) for t in task.memory_types]
                except Exception as e:
                    raise ValueError(f"Invalid memory_types: {e}") from e

            start_time = time.time()
            memories = searcher.search_memories(
                player_id=task.player_id,
                npc_id=task.npc_id,
                query=task.content,
                top_k=task.top_k or 5,
                memory_types=types,
                time_range_days=task.time_range_days,
            )
            query_time_ms = (time.time() - start_time) * 1000

            write_reply(task.task_id, {
                "status": "ok",
                "op": "search",
                "task_id": task.task_id,
                "total": len(memories),
                "query_time_ms": query_time_ms,
                "memories": [
                    {
                        "id": m.id,
                        "player_id": m.player_id,
                        "npc_id": m.npc_id,
                        "memory_type": m.memory_type.value,
                        "content": m.content,
                        "importance": m.importance,
                        "emotion_tags": m.emotion_tags,
                        "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                        "game_context": m.game_context or {},
                    }
                    for m in memories
                ],
            })
            return True

        # Default: op=index
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

        embedder = get_embedder()
        memory.content_vector = embedder.embed(memory.content)

        es = get_es_client()
        doc = memory.to_es_doc()

        start_time = time.time()
        # Note: routing parameter not supported in Elastic Cloud Serverless mode
        es.index(
            index=get_env("INDEX_ALIAS"),
            id=doc["_id"],
            body={k: v for k, v in doc.items() if not k.startswith("_")}
        )
        observe_bulk_latency(time.time() - start_time)

        write_reply(task.task_id, {
            "status": "ok",
            "op": "index",
            "task_id": task.task_id,
            "memory_id": task.task_id,
        })

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
