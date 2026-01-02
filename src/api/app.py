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
from .dependencies import get_memory_service, get_publisher, get_es_client
from src.memory import MemoryType
from src.indexing import IndexTask
from src.metrics import inc_cache_hit, inc_cache_miss


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
    Create a new memory (async indexing via Pub/Sub)

    The memory will be queued for processing by the Worker service,
    which generates embeddings and indexes to Elasticsearch.

    **Flow**:
    1. Create IndexTask with auto-generated task_id
    2. Publish to Pub/Sub topic
    3. Return task_id immediately (async processing)

    **Idempotency**: task_id is used as ES document _id,
    ensuring duplicate messages result in overwrite, not duplicate inserts.
    """
    publisher = get_publisher()

    if publisher is None:
        raise HTTPException(
            status_code=503,
            detail="Async indexing not available. Set INDEX_ASYNC_ENABLED=true"
        )

    task = IndexTask.create(
        player_id=request.player_id,
        npc_id=request.npc_id,
        content=request.content,
        memory_type=request.memory_type.value,
        importance=request.importance,
        emotion_tags=request.emotion_tags,
        game_context=request.game_context,
    )

    try:
        publisher.publish(task)
        return MemoryCreateResponse(
            task_id=task.task_id,
            status="queued",
            message="Memory queued for indexing",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {e}")


@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_memories(
    player_id: str = Query(..., description="Player ID"),
    npc_id: str = Query(..., description="NPC ID"),
    query: str = Query(..., min_length=1, description="Search query text"),
    top_k: int = Query(5, ge=1, le=50, description="Maximum number of results"),
    memory_types: Optional[str] = Query(
        None,
        description="Comma-separated memory types filter (e.g., 'quest,dialogue')",
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
    start_time = time.time()
    service = get_memory_service()

    # Parse memory types filter
    types: Optional[List[MemoryType]] = None
    if memory_types:
        try:
            types = [MemoryType(t.strip()) for t in memory_types.split(",")]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid memory type: {e}")

    try:
        memories = service.search_memories(
            player_id=player_id,
            npc_id=npc_id,
            query=query,
            top_k=top_k,
            memory_types=types,
            time_range_days=time_range_days,
        )

        query_time_ms = (time.time() - start_time) * 1000

        return SearchResponse(
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
                for m in memories
            ],
            total=len(memories),
            query_time_ms=query_time_ms,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


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
