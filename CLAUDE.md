# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

- **Python Environment**: Use `py312` conda environment
  ```bash
  conda activate py312
  pip install -r services/api/requirements.txt
  ```
- **Local Infrastructure**: Docker Compose for ES + Redis
  ```bash
  docker-compose up -d es-coordinator kibana redis  # Lightweight dev setup
  ```
- **Context Retrieval**: Always use ace-tools for codebase context search before making changes

## Common Commands

### Local Development

```bash
# Initialize ES index
cd services/api
python -c "from src.es_client import create_es_client, initialize_index; initialize_index(create_es_client())"

# Start API service (port 8000)
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload

# Start Worker service (port 8080, for async mode)
cd ../worker
uvicorn src.indexing.push_app:app --host 0.0.0.0 --port 8080 --reload
```

### Cloud Deployment (asia-southeast1)

```bash
# Deploy API service
gcloud run deploy npc-memory-api \
  --source services/api \
  --region asia-southeast1

# Deploy Worker service
gcloud run deploy npc-memory-worker \
  --source services/worker \
  --region asia-southeast1 \
  --set-env-vars "PUBSUB_PROJECT_ID=$(gcloud config get-value project),MAX_INFLIGHT_TASKS=4" \
  --min-instances 0 --max-instances 10 --concurrency 4

# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=npc-memory-api" --limit=50
```

### Benchmark

```bash
# Run performance benchmark against Cloud Run
BENCH_API_BASE_URL=https://npc-memory-api-xxx.asia-southeast1.run.app python examples/benchmark.py
```

## Architecture Overview

```
Client -> API Service (FastAPI) -> Pub/Sub -> Worker Service -> Elasticsearch
              |                                    |
              +------------ Redis <----------------+
                        (cache + reply)
```

### Key Modules

| Directory | Purpose |
|-----------|---------|
| `services/api/src/api/` | REST API (FastAPI) - entry point `app.py` |
| `services/*/src/memory/` | Core memory module: models, embedding, search, write |
| `services/worker/src/indexing/` | Async indexing: Pub/Sub client, Push Worker |
| `services/*/src/memory_service.py` | Facade layer composing all modules |

### Design Patterns

- **Facade**: `NPCMemoryService` as unified interface
- **Strategy**: Sync/Async write switching via `pubsub_publisher` parameter
- **Factory**: `IndexTask.create()` for task generation

### Hybrid Search (BM25 + Vector + RRF)

Located in `services/*/src/memory/search.py`:
1. BM25 and Vector search execute in parallel (ThreadPoolExecutor)
2. RRF fusion: `score = sum(1 / (k + rank_i))`, k=60
3. Memory decay: `importance *= exp(-0.01 * days)`

### Async Indexing Flow

1. API publishes `IndexTask` to Pub/Sub
2. Worker receives via HTTP push (`POST /pubsub/push`)
3. Worker generates embedding, indexes to ES
4. Worker writes result to Redis (`LPUSH reply:{task_id}`)
5. API waits on Redis (`BRPOP reply:{task_id}`)

## Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ES_URL` | http://localhost:9200 | Elasticsearch URL |
| `ES_API_KEY` | - | Elastic Cloud API Key |
| `INDEX_ASYNC_ENABLED` | false | Enable async indexing |
| `REDIS_URL` | - | Redis URL (required for async) |
| `EMBEDDING_API_KEY` | - | Embedding service API key |
| `EMBEDDING_BASE_URL` | - | OpenAI-compatible embedding API |
| `EMBEDDING_MODEL` | qwen3-embedding-8b | Embedding model name |
| `MAX_INFLIGHT_TASKS` | 4 | Worker concurrency (backpressure) |
| `REQUEST_TIMEOUT_SECONDS` | 25 | API request-reply timeout |

## API Endpoints

| Service | Endpoint | Description |
|---------|----------|-------------|
| API | `POST /memories` | Create memory (request-reply) |
| API | `GET /search` | Hybrid search |
| API | `GET /context` | Prepare LLM context (RAG) |
| Worker | `POST /pubsub/push` | Handle Pub/Sub push delivery |
| Both | `GET /health`, `/ready`, `/metrics` | Health/readiness/monitoring |

## Elasticsearch

- Index alias: `npc_memories`
- Vector dims: 1024 (Qwen3)
- HNSW config: m=16, ef_construction=100
- Sharding: 30 shards, 1 replica (production)

## Infrastructure

- **Elastic Cloud**: Serverless, asia-southeast1
- **Google Cloud Pub/Sub**: Push subscription with DLQ
- **Redis**: Query cache (TTL 5min) + Embedding cache (TTL 7d) + Request-reply
