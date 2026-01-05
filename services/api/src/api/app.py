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

import os
import time
import asyncio
from typing import Optional, List

from fastapi import FastAPI, Query, HTTPException, Depends, Response

from .schemas import (
    MemoryCreateRequest,
    MemoryCreateResponse,
    MemoryResponse,
    SearchResponse,
    HealthResponse,
    ContextResponse,
    MemoryTypeEnum,
)
from .dependencies import get_memory_service, get_publisher, get_es_client, get_reply_store
from src.memory import MemoryType
from src.indexing import IndexTask
from src.metrics import inc_cache_hit, inc_cache_miss
from src import get_env_int

REQUEST_TIMEOUT_SECONDS = get_env_int("REQUEST_TIMEOUT_SECONDS")


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
- **Strategy**: Sync/Async write switching
- **Factory**: IndexTask.create() for task generation
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.post("/memories", response_model=MemoryCreateResponse, tags=["Memory"])
async def create_memory(request: MemoryCreateRequest):
    """
    Create a new memory (request-reply via Pub/Sub + Worker).

    The API service publishes an indexing task to Pub/Sub, then blocks waiting
    for the Worker to write the result to Redis.
    """
    publisher = get_publisher()
    reply_store = get_reply_store()

    if publisher is None or reply_store is None:
        raise HTTPException(
            status_code=503,
            detail="Async indexing not available. Ensure INDEX_ASYNC_ENABLED=true and REDIS_URL is set"
        )

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

    if publisher is None or reply_store is None:
        raise HTTPException(
            status_code=503,
            detail="Async search not available. Ensure INDEX_ASYNC_ENABLED=true and REDIS_URL is set"
        )

    # Parse memory types filter
    types: Optional[List[MemoryType]] = None
    type_values: Optional[List[str]] = None
    if memory_types:
        try:
            type_values = [t.strip() for t in memory_types.split(",") if t.strip()]
            types = [MemoryType(t) for t in type_values]
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
    service = get_memory_service()

    try:
        context = service.prepare_context_for_llm(
            player_id=player_id,
            npc_id=npc_id,
            current_query=query,
            max_memories=max_memories,
        )

        return ContextResponse(
            memories=[
                MemoryResponse(
                    id=m.id,
                    player_id=m.player_id,
                    npc_id=m.npc_id,
                    memory_type=m.memory_type.value,
                    content=m.content,
                    importance=m.importance,
                    emotion_tags=m.emotion_tags,
                    timestamp=m.timestamp,
                    game_context=m.game_context or {},
                )
                for m in context.memories
            ],
            summary=context.summary,
            total_interactions=context.total_interactions,
            last_interaction=context.last_interaction,
            relationship_score=context.relationship_score,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context preparation failed: {e}")


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
