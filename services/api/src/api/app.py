"""
NPC Memory RAG API Service

REST API for memory write (async via Pub/Sub) and hybrid search.
Designed for Cloud Run deployment as a separate service from Worker.

Architecture:
    Client -> API Service -> Pub/Sub -> Worker Service -> ES
                  |                          |
                  +---------- ES <-----------+
                       (direct search)
"""

import asyncio
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, Query, HTTPException, Response

from .schemas import (
    MemoryCreateRequest,
    MemoryCreateResponse,
    MemoryResponse,
    SearchResponse,
    HealthResponse,
    ContextResponse,
)
from .dependencies import get_publisher, get_es_client, get_reply_store
from src.memory import MemoryType
from src.indexing import IndexTask
from src import get_env_int

REQUEST_TIMEOUT_SECONDS = get_env_int("REQUEST_TIMEOUT_SECONDS")

def _build_summary(memories: List[dict]) -> str:
    """Build concise summary of memories."""
    if not memories:
        return "No previous interactions"

    type_counts: dict[str, int] = {}
    emotions: List[str] = []
    seen_emotions = set()

    for m in memories:
        mtype = str(m.get("memory_type") or "")
        if mtype:
            type_counts[mtype] = type_counts.get(mtype, 0) + 1

        for e in (m.get("emotion_tags") or []):
            if e not in seen_emotions:
                seen_emotions.add(e)
                emotions.append(e)

    summary_parts = [f"{count}次{mtype}记忆" for mtype, count in type_counts.items()]
    summary = "、".join(summary_parts) if summary_parts else "No previous interactions"

    top_emotions = emotions[:3]
    if top_emotions:
        summary += f"，主要情感：{', '.join(top_emotions)}"
    return summary


def _relationship_score(memories: List[dict]) -> float:
    """Calculate relationship score from -1 to 1."""
    if not memories:
        return 0.0

    positive_emotions = {"感谢", "信任", "友好", "喜悦", "赞赏"}
    negative_emotions = {"愤怒", "失望", "怀疑", "恐惧", "厌恶"}

    positive_count = 0
    negative_count = 0

    for m in memories:
        for e in (m.get("emotion_tags") or []):
            if e in positive_emotions:
                positive_count += 1
            elif e in negative_emotions:
                negative_count += 1

    total = positive_count + negative_count
    if total == 0:
        return 0.0
    return (positive_count - negative_count) / total


app = FastAPI(
    title="NPC Memory RAG API",
    description="""
NPC Memory RAG system API for game AI memory management.

## Features

- **Hybrid Search**: BM25 + Vector + RRF (Reciprocal Rank Fusion)
- **Memory Decay**: Time-based importance decay simulating human forgetting curve
- **Async Indexing**: Pub/Sub based distributed indexing for high throughput
- **Redis Cache**: Query result caching with TTL

## Architecture

```
API Service          Worker Service
    |                     |
    +---> Pub/Sub ------->+
    |                     |
    +<------ ES <---------+
```

## Design Patterns

- **Facade**: NPCMemoryService as unified interface
- **Factory**: IndexTask.create() for task generation
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

@app.on_event("startup")
async def _startup_fail_fast():
    """Fail fast on missing dependencies/config at startup."""
    get_publisher()
    get_reply_store()


@app.post("/memories", response_model=MemoryCreateResponse, tags=["Memory"])
async def create_memory(request: MemoryCreateRequest):
    """
    Create a new memory (request-reply via Pub/Sub + Worker).

    The API service publishes an indexing task to Pub/Sub, then blocks waiting
    for the Worker to write the result to Redis.
    """
    publisher = get_publisher()
    reply_store = get_reply_store()

    task = IndexTask.create(
        player_id=request.player_id,
        npc_id=request.npc_id,
        content=request.content,
        memory_type=request.memory_type.value,
        op="index",
        importance=request.importance,
        emotion_tags=request.emotion_tags,
        game_context=request.game_context,
    )

    try:
        publisher.publish(task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {e}")

    try:
        result = await asyncio.to_thread(reply_store.wait, task.task_id, REQUEST_TIMEOUT_SECONDS)
        if result is None:
            raise HTTPException(status_code=504, detail=f"Worker timeout (task_id={task.task_id})")
        if result.get("status") != "ok":
            raise HTTPException(status_code=500, detail=f"Worker failed: {result}")

        return MemoryCreateResponse(
            task_id=task.task_id,
            memory_id=result.get("memory_id", task.task_id),
            status="completed",
            message="Memory indexed",
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Failed to wait for worker: {e}")


@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_memories(
    player_id: str = Query(..., description="Player ID"),
    npc_id: str = Query(..., description="NPC ID"),
    query: str = Query(..., min_length=1, description="Search query text"),
    top_k: int = Query(5, ge=1, le=50, description="Maximum number of results"),
    memory_types: Optional[str] = Query(
        None,
        description="Comma-separated preferred memory types (soft preference, e.g., 'quest,dialogue')",
    ),
    time_range_days: Optional[int] = Query(
        None, ge=1, description="Filter memories within N days"
    ),
):
    """
    Hybrid search memories with BM25 + Vector + RRF fusion

    **Algorithm**:
    1. Parallel execution of BM25 (keyword) and Vector (semantic) search
    2. RRF fusion: `score = sum(1 / (k + rank_i))` where k=60
    3. Memory decay: `importance *= exp(-lambda * days)` where lambda=0.01

    **Caching**: Results are cached in Redis with 5-minute TTL.
    """
    publisher = get_publisher()
    reply_store = get_reply_store()

    # Parse memory types filter
    type_values: Optional[List[str]] = None
    if memory_types:
        try:
            type_values = [t.strip() for t in memory_types.split(",") if t.strip()]
            # Validate provided types.
            for t in type_values:
                MemoryType(t)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid memory type: {e}")

    try:
        task = IndexTask.create(
            player_id=player_id,
            npc_id=npc_id,
            content=query,            # search query is stored in content
            memory_type="search",     # ignored by worker for op=search
            op="search",
            top_k=top_k,
            memory_types=type_values,
            time_range_days=time_range_days,
        )
        publisher.publish(task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue search task: {e}")

    try:
        result = await asyncio.to_thread(reply_store.wait, task.task_id, REQUEST_TIMEOUT_SECONDS)
        if result is None:
            raise HTTPException(status_code=504, detail=f"Worker timeout (task_id={task.task_id})")
        if result.get("status") != "ok":
            raise HTTPException(status_code=500, detail=f"Worker failed: {result}")

        return SearchResponse(
            memories=[MemoryResponse(**m) for m in result.get("memories", [])],
            total=int(result.get("total", 0)),
            query_time_ms=float(result.get("query_time_ms", 0.0)),
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Failed to wait for worker: {e}")


@app.get("/context", response_model=ContextResponse, tags=["Search"])
async def get_context_for_llm(
    player_id: str = Query(..., description="Player ID"),
    npc_id: str = Query(..., description="NPC ID"),
    query: str = Query(..., min_length=1, description="Current query/topic"),
    max_memories: int = Query(10, ge=1, le=50, description="Maximum memories to include"),
):
    """
    Prepare memory context for LLM (RAG use case)

    Returns:
    - Relevant memories sorted by importance
    - Summary of interaction history
    - Relationship score based on emotion tags
    """
    publisher = get_publisher()
    reply_store = get_reply_store()

    try:
        task = IndexTask.create(
            player_id=player_id,
            npc_id=npc_id,
            content=query,
            memory_type="search",
            op="search",
            top_k=max_memories,
        )
        publisher.publish(task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue context task: {e}")

    try:
        result = await asyncio.to_thread(reply_store.wait, task.task_id, REQUEST_TIMEOUT_SECONDS)
        if result is None:
            raise HTTPException(status_code=504, detail=f"Worker timeout (task_id={task.task_id})")
        if result.get("status") != "ok":
            raise HTTPException(status_code=500, detail=f"Worker failed: {result}")

        memories = result.get("memories", []) or []
        last_ts = None
        if memories:
            ts = memories[0].get("timestamp")
            if ts:
                try:
                    last_ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    last_ts = None

        return ContextResponse(
            memories=[MemoryResponse(**m) for m in memories],
            summary=_build_summary(memories),
            total_interactions=len(memories),
            last_interaction=last_ts,
            relationship_score=_relationship_score(memories),
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Failed to wait for worker: {e}")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """
    Health check endpoint (liveness probe)

    Always returns healthy if the service is running.
    """
    return HealthResponse(status="healthy")


@app.get("/ready", response_model=HealthResponse, tags=["Health"])
async def ready():
    """
    Readiness check endpoint (readiness probe)

    Verifies Elasticsearch connection is available.
    Returns 503 if ES is not reachable.
    """
    try:
        es = get_es_client()
        if es.ping():
            return HealthResponse(status="ready")
        else:
            raise HTTPException(status_code=503, detail="ES not reachable")
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/metrics", tags=["Health"])
async def metrics():
    """
    Expose Prometheus metrics

    Includes:
    - npc_memory_cache_hits_total
    - npc_memory_cache_misses_total
    - npc_memory_embedding_requests_total
    - npc_memory_embedding_latency_seconds
    """
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response(
            content="# prometheus_client not installed", media_type="text/plain"
        )
