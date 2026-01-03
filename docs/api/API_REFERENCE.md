# NPC Memory Push Worker API Reference

## Overview

NPC Memory Push Worker is a FastAPI service that processes memory indexing tasks from Google Cloud Pub/Sub. It generates embeddings using ModelScope Qwen3 and indexes memories to Elasticsearch.

**Base URL**: `https://npc-memory-worker-{project_number}.asia-southeast1.run.app`

**Local Development**: `http://localhost:8080`

## Architecture

```
Game Server -> Pub/Sub Topic -> Push Subscription -> Push Worker API -> Elasticsearch
                                       |                   |
                                       |            ModelScope Qwen3
                                       |           (Embedding Generation)
                                       |
                                       └── 429 backpressure (retry later)
```

**Backpressure**: Worker uses `MAX_INFLIGHT_TASKS` semaphore to limit concurrency. Returns 429 when at capacity, triggering Pub/Sub retry.

## Endpoints

### POST /pubsub/push

Handle Pub/Sub push delivery.

**Request**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| message.data | string (base64) | Yes | Base64-encoded IndexTask JSON |
| message.messageId | string | No | Pub/Sub message ID |
| subscription | string | No | Full subscription name |

**Request Example**

```bash
curl -X POST https://npc-memory-worker-xxx.asia-southeast1.run.app/pubsub/push \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "data": "eyJ0YXNrX2lkIjoidGVzdC0wMDEiLCJwbGF5ZXJfaWQiOiJwbGF5ZXJfMSIsIm5wY19pZCI6Im5wY19ibGFja3NtaXRoIiwibWVtb3J5X3R5cGUiOiJkaWFsb2d1ZSIsImNvbnRlbnQiOiJUaGUgYmxhY2tzbWl0aCBvZmZlcmVkIG1lIGEgc3dvcmQuIiwiaW1wb3J0YW5jZSI6MC44LCJlbW90aW9uX3RhZ3MiOlsiaGFwcHkiXSwidGltZXN0YW1wIjoiMjAyNS0wMS0wMVQwMDowMDowMCIsImdhbWVfY29udGV4dCI6e319"
    },
    "subscription": "projects/npc-memory-rag/subscriptions/index-tasks-push"
  }'
```

**IndexTask JSON Schema (before base64 encoding)**

```json
{
  "task_id": "test-001",
  "player_id": "player_1",
  "npc_id": "npc_blacksmith",
  "memory_type": "dialogue",
  "content": "The blacksmith offered me a legendary sword for 1000 gold.",
  "importance": 0.8,
  "emotion_tags": ["happy", "excited"],
  "timestamp": "2025-01-01T00:00:00",
  "game_context": {
    "location": "village_smithy",
    "quest": "find_sword"
  }
}
```

**IndexTask Fields**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| task_id | string | Yes | - | Unique task ID (used as ES document ID) |
| player_id | string | Yes | - | Player identifier |
| npc_id | string | Yes | - | NPC identifier |
| content | string | Yes | - | Memory content text |
| memory_type | string | Yes | - | One of: dialogue, quest, trade, gift, combat, emotion |
| timestamp | string | Yes | - | ISO 8601 datetime |
| importance | float | No | 0.5 | Importance score (0-1) |
| emotion_tags | array | No | [] | Emotion tags |
| game_context | object | No | {} | Additional context |

**Response**

| Status | Description |
|--------|-------------|
| 200 | Message processed successfully (ack) |
| 400 | Invalid message format (ack, no retry) |
| 429 | At capacity, backpressure (will retry) |
| 500 | Processing failed (nack, will retry) |

**Success Response (200)**

```json
{
  "status": "ok",
  "task_id": "test-001"
}
```

**Error Response (400/500)**

```json
{
  "detail": "Invalid task format: Expecting property name"
}
```

---

### GET /health

Basic health check endpoint.

**Request**

```bash
curl https://npc-memory-worker-xxx.asia-southeast1.run.app/health
```

**Response (200)**

```json
{
  "status": "healthy"
}
```

---

### GET /ready

Readiness check that verifies Elasticsearch connection.

**Request**

```bash
curl https://npc-memory-worker-xxx.asia-southeast1.run.app/ready
```

**Response (200)**

```json
{
  "status": "ready"
}
```

**Response (503)**

```json
{
  "detail": "ES not reachable"
}
```

---

### GET /metrics

Prometheus metrics endpoint.

**Request**

```bash
curl https://npc-memory-worker-xxx.asia-southeast1.run.app/metrics
```

**Response (200)**

```text
# HELP npc_memory_worker_messages_pulled_total Total messages pulled
# TYPE npc_memory_worker_messages_pulled_total counter
npc_memory_worker_messages_pulled_total 100.0

# HELP npc_memory_worker_messages_processed_total Total messages processed
# TYPE npc_memory_worker_messages_processed_total counter
npc_memory_worker_messages_processed_total{status="success"} 95.0
npc_memory_worker_messages_processed_total{status="error"} 5.0

# HELP npc_memory_worker_bulk_latency_seconds ES bulk write latency
# TYPE npc_memory_worker_bulk_latency_seconds histogram
npc_memory_worker_bulk_latency_seconds_bucket{le="0.1"} 80.0
npc_memory_worker_bulk_latency_seconds_bucket{le="0.5"} 95.0
npc_memory_worker_bulk_latency_seconds_bucket{le="1.0"} 100.0

# HELP npc_memory_embedding_latency_seconds Embedding generation latency
# TYPE npc_memory_embedding_latency_seconds histogram
npc_memory_embedding_latency_seconds_bucket{le="1.0"} 50.0
npc_memory_embedding_latency_seconds_bucket{le="5.0"} 95.0
npc_memory_embedding_latency_seconds_bucket{le="10.0"} 100.0
```

**Available Metrics**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| npc_memory_worker_messages_pulled_total | Counter | - | Total messages pulled from Pub/Sub |
| npc_memory_worker_messages_processed_total | Counter | status | Total messages processed (success/error) |
| npc_memory_worker_bulk_latency_seconds | Histogram | - | ES write latency |
| npc_memory_embedding_latency_seconds | Histogram | - | Embedding generation latency |
| npc_memory_embedding_requests_total | Counter | status | Embedding requests (success/error) |

---

## Data Models

### MemoryType Enum

| Value | Description |
|-------|-------------|
| dialogue | NPC dialogue interaction |
| quest | Quest-related memory |
| trade | Trading transaction |
| gift | Gift exchange |
| combat | Combat event |
| emotion | Emotional state change |

### Memory Document (Elasticsearch)

```json
{
  "_id": "test-001",
  "player_id": "player_1",
  "npc_id": "npc_blacksmith",
  "memory_type": "dialogue",
  "content": "The blacksmith offered me a legendary sword.",
  "content_vector": [0.1, 0.2, ...],
  "emotion_tags": ["happy"],
  "importance": 0.8,
  "timestamp": "2025-01-01T00:00:00",
  "game_context": {
    "location": "village_smithy"
  }
}
```

---

## Error Handling

### Error Response Format

All error responses follow this format:

```json
{
  "detail": "Error message description"
}
```

### Common Errors

| Status | Error | Cause | Solution |
|--------|-------|-------|----------|
| 400 | Missing message data | Pub/Sub message has no data field | Check message format |
| 400 | Invalid task format | JSON parsing failed | Verify IndexTask JSON structure |
| 429 | At capacity, retry later | MAX_INFLIGHT_TASKS reached | Normal backpressure, Pub/Sub will retry |
| 500 | Processing failed | Embedding or ES write failed | Check logs for details |
| 503 | ES not reachable | Elasticsearch connection failed | Check ES_URL and ES_API_KEY |

---

## Publishing Messages

### Using gcloud CLI

```bash
# Publish a test message
gcloud pubsub topics publish index-tasks --message='{
  "task_id": "test-001",
  "player_id": "player_1",
  "npc_id": "npc_blacksmith",
  "memory_type": "dialogue",
  "content": "The blacksmith offered me a sword.",
  "importance": 0.8,
  "emotion_tags": ["happy"],
  "timestamp": "2025-01-01T00:00:00",
  "game_context": {}
}'
```

### Using Python SDK

```python
from google.cloud import pubsub_v1
import json

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path("npc-memory-rag", "index-tasks")

task = {
    "task_id": "test-001",
    "player_id": "player_1",
    "npc_id": "npc_blacksmith",
    "memory_type": "dialogue",
    "content": "The blacksmith offered me a sword.",
    "importance": 0.8,
    "emotion_tags": ["happy"],
    "timestamp": "2025-01-01T00:00:00",
    "game_context": {}
}

data = json.dumps(task).encode("utf-8")
future = publisher.publish(topic_path, data)
print(f"Published message ID: {future.result()}")
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| ES_URL | Yes | http://localhost:9200 | Elasticsearch URL |
| ES_API_KEY | No | - | Elastic Cloud API Key |
| EMBEDDING_API_KEY | Yes | - | Embedding API Key (preferred) |
| EMBEDDING_BASE_URL | No | https://your-embedding-api.com/v1 | Embedding API URL |
| EMBEDDING_MODEL | No | qwen3-embedding-8b | Embedding model name |
| MODELSCOPE_API_KEY | No | - | Legacy alias for EMBEDDING_API_KEY |
| INDEX_ALIAS | No | npc_memories | ES index alias |
| MAX_INFLIGHT_TASKS | No | 4 | Max concurrent tasks (backpressure) |
| ES_ROUTING_ENABLED | No | false | Enable routing (disable for Serverless) |
| PORT | No | 8080 | HTTP server port |

---

## Deployment

See [CLAUDE.md](../../CLAUDE.md) for complete Cloud Run deployment instructions.

**Quick Deploy**

```bash
gcloud run deploy npc-memory-worker \
  --source . \
  --region asia-southeast1 \
  --set-env-vars "PUBSUB_PROJECT_ID=$(gcloud config get-value project),MAX_INFLIGHT_TASKS=4" \
  --set-secrets "ES_URL=es-url:latest,ES_API_KEY=es-api-key:latest,MODELSCOPE_API_KEY=modelscope-api-key:latest" \
  --min-instances 0 \
  --max-instances 10 \
  --concurrency 4 \
  --allow-unauthenticated
```
