# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

- **Python Environment**: Use `py312` conda environment
  ```bash
  conda activate py312
  pip install -r services/api/requirements.txt
  ```
- **Environment Variables**: Use `.env` for local development (recommended)
  ```bash
  cp env.example .env
  ```
  PowerShell:
  ```bash
  Copy-Item env.example .env
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

### Cloud Run 部署踩坑记录（重要，避免再次翻车）

只记三条：**PowerShell 命令差异**、**Cloud Run 不读本地 `.env`**、**缺 env 会在 import 阶段崩（表象是“没监听 PORT=8080”）**。

```bash
gcloud auth list
gcloud config get-value project --quiet
gcloud config get-value run/region --quiet
```

#### Cloud Run：启动必需 env（API/Worker 都要有）
- `ES_URL` / `ES_API_KEY`（推荐 Secret） + `INDEX_ALIAS`
- `INDEX_VECTOR_DIMS` + `SEARCH_THREAD_POOL_SIZE` + `METRICS_PORT`
- `ES_ROUTING_ENABLED`
- `REDIS_URL`（request-reply + cache）
- `PUBSUB_PROJECT_ID` + `PUBSUB_TOPIC` + `PUBSUB_PRODUCER`
- `EMBEDDING_PROVIDER` + `EMBEDDING_BASE_URL` + `EMBEDDING_MODEL`
- `EMBEDDING_ALLOW_STUB` + `EMBEDDING_CACHE_ENABLED` + `EMBEDDING_TIMEOUT` + `EMBEDDING_MAX_RETRIES`
- `MODELSCOPE_API_KEY` 或 `EMBEDDING_API_KEY`（推荐 Secret）

#### Cloud Run：推荐部署（把 env 显式带上）

```bash
gcloud run deploy npc-memory-api \
  --source services/api \
  --region asia-southeast1 \
  --set-secrets "ES_URL=es-url:latest,ES_API_KEY=es-api-key:latest,MODELSCOPE_API_KEY=modelscope-api-key:latest" \
  --update-env-vars "INDEX_ALIAS=npc_memories,INDEX_VECTOR_DIMS=4096,SEARCH_THREAD_POOL_SIZE=16,METRICS_PORT=8000,ES_ROUTING_ENABLED=false,REDIS_URL=redis-url,PUBSUB_PROJECT_ID=$(gcloud config get-value project),PUBSUB_TOPIC=index-tasks,PUBSUB_PRODUCER=api,EMBEDDING_PROVIDER=openai_compatible,EMBEDDING_BASE_URL=https://api.bltcy.ai/v1,EMBEDDING_MODEL=qwen3-embedding-8b,EMBEDDING_ALLOW_STUB=false,EMBEDDING_CACHE_ENABLED=false,EMBEDDING_TIMEOUT=30,EMBEDDING_MAX_RETRIES=3,REQUEST_TIMEOUT_SECONDS=55,REPLY_TTL_SECONDS=60,CACHE_TTL_SECONDS=300" \
  --quiet
```

```bash
gcloud run deploy npc-memory-worker \
  --source services/worker \
  --region asia-southeast1 \
  --set-secrets "ES_URL=es-url:latest,ES_API_KEY=es-api-key:latest,MODELSCOPE_API_KEY=modelscope-api-key:latest" \
  --update-env-vars "INDEX_ALIAS=npc_memories,INDEX_VECTOR_DIMS=4096,SEARCH_THREAD_POOL_SIZE=16,METRICS_PORT=8000,ES_ROUTING_ENABLED=false,REDIS_URL=redis-url,PUBSUB_PROJECT_ID=$(gcloud config get-value project),PUBSUB_TOPIC=index-tasks,PUBSUB_PRODUCER=worker,EMBEDDING_PROVIDER=openai_compatible,EMBEDDING_BASE_URL=https://api.bltcy.ai/v1,EMBEDDING_MODEL=qwen3-embedding-8b,EMBEDDING_ALLOW_STUB=false,EMBEDDING_CACHE_ENABLED=false,EMBEDDING_TIMEOUT=30,EMBEDDING_MAX_RETRIES=3,MAX_INFLIGHT_TASKS=4,REPLY_TTL_SECONDS=60" \
  --quiet
```

#### 部署后验收
- `GET /health` / `GET /ready`

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
| `REDIS_URL` | - | Redis URL (required) |
| `PUBSUB_PROJECT_ID` | - | GCP project ID (required) |
| `PUBSUB_TOPIC` | - | Pub/Sub topic name (required) |
| `PUBSUB_PRODUCER` | - | Pub/Sub message producer tag (required) |
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
