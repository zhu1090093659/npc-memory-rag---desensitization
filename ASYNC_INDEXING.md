# 异步索引构建指南

本文档说明如何使用队列驱动的异步处理（Pub/Sub Push + Cloud Run 自动伸缩），并通过 Redis 实现 request-reply，让客户端请求可以同步拿到结果。

## 架构概览

```
写入/查询入口 (API)
    │
    └─► 发布到 Pub/Sub Topic（task_id 作为关联 ID）
            │
            └─► Pub/Sub Push 投递到 Worker
                    │
                    ├─► 并发闸门检查（满载返回 429）
                    ├─► 执行 index 或 search
                    ├─► 写入 ES
                    ├─► 写入 Redis reply:{task_id}
                    └─► API 侧 BRPOP 阻塞等待并返回给客户端
```

## 核心机制

**Backpressure 实现**：Worker 使用 `MAX_INFLIGHT_TASKS` 信号量控制并发，满载时返回 429，Pub/Sub 会自动重试。

**自动伸缩**：Cloud Run 根据请求队列自动扩缩容，配合 `min-instances=0` 实现"空闲缩零、积压扩容"。

## 环境变量配置

### Worker 配置

```bash
# Elasticsearch
export ES_URL="https://your-es-host:443"
export ES_API_KEY="your-api-key"           # Elastic Cloud 认证

# Embedding
export MODELSCOPE_API_KEY="your-key"

# request-reply (required)
export REDIS_URL="redis://localhost:6379/0"
export REQUEST_TIMEOUT_SECONDS="25"         # API wait timeout
export REPLY_TTL_SECONDS="60"               # reply TTL

# 并发控制
export MAX_INFLIGHT_TASKS="4"              # 单实例最大并发任务数
export PORT="8080"                         # HTTP 端口
```

### 写入端配置

```bash
# Pub/Sub
export PUBSUB_PROJECT_ID="your-gcp-project-id"
export PUBSUB_TOPIC="index-tasks"

# 异步索引开关（默认关闭）
export INDEX_ASYNC_ENABLED="false"

# Serverless ES 禁用 routing（默认禁用）
export ES_ROUTING_ENABLED="false"
```

## 快速开始（本地开发）

### 1. 启动本地 Elasticsearch

```bash
docker-compose up -d
curl http://localhost:9200  # 验证
```

### 2. 初始化索引

```bash
python examples/init_es.py
```

### 3. 启动 Push Worker

```bash
python examples/run_worker.py
```

Worker 启动后会监听 `http://localhost:8080`，等待 Pub/Sub 推送。

### 4. 发布测试任务

```bash
export INDEX_ASYNC_ENABLED="true"
python examples/publish_task.py
```

## 使用方式

### 同步模式（默认）

```python
from src.es_client import create_es_client
from src.memory import EmbeddingService, Memory, MemoryType
from src.memory_service import NPCMemoryService

# 初始化
es = create_es_client()
embedder = EmbeddingService()
service = NPCMemoryService(es, embedder)

# 直接写入 ES
memory = Memory(
    id="mem_001",
    player_id="player_123",
    npc_id="npc_456",
    memory_type=MemoryType.DIALOGUE,
    content="玩家与NPC的对话内容",
    importance=0.7
)
service.add_memory(memory)
```

### 异步模式（Pub/Sub + Worker）

```python
from src.indexing import PubSubPublisher

# 初始化时传入 publisher
publisher = PubSubPublisher()
service = NPCMemoryService(es, embedder, pubsub_publisher=publisher)

# 方式1: 使用环境变量控制
# export INDEX_ASYNC_ENABLED="true"
service.add_memory(memory)

# 方式2: 显式指定异步
service.add_memory(memory, async_index=True)
```

## 幂等性保证

Worker 使用 `task_id` 作为 ES 的 `_id`，确保：
- 重复消息不会创建重复记录
- 消息重试是安全的

## 错误处理

### Worker 错误处理策略

1. **解析失败**：消息被 nack，会重试或进入死信队列
2. **Embedding 失败**：整批任务失败，不 ack
3. **部分 ES 写入失败**：记录错误日志，成功部分正常处理

### 监控建议

- 监控 Pub/Sub 订阅的未 ack 消息数
- 监控 Worker 的处理成功率
- 监控 ES 索引速率

## 性能调优

### Worker 并发控制

```bash
# 单实例最大并发任务数（默认 4）
export MAX_INFLIGHT_TASKS="8"
```

满载时返回 429，触发 Pub/Sub 重试，消息留在队列等待 Cloud Run 扩容。

### 横向扩展

Cloud Run 根据请求队列自动扩容，无需手动管理。关键参数：

- `concurrency`: 单实例并发请求数（建议与 MAX_INFLIGHT_TASKS 一致）
- `max-instances`: 最大实例数上限
- `min-instances=0`: 允许缩容到零

## 回滚到同步模式

设置环境变量或不传入 publisher：
```bash
export INDEX_ASYNC_ENABLED="false"
```

## 常见问题

### Q: Worker 返回 429 怎么办？

A: 这是正常的 backpressure 机制。Pub/Sub 会自动重试，Cloud Run 会自动扩容。如果持续出现，可以：
1. 增加 `MAX_INFLIGHT_TASKS`
2. 增加 `max-instances`

### Q: 如何查看 Pub/Sub 消息堆积？

A: 使用 GCP Console 或 gcloud CLI：
```bash
gcloud pubsub subscriptions describe index-tasks-push
```

### Q: 本地开发如何测试 Pub/Sub？

A: 可以使用 Pub/Sub Emulator：
```bash
gcloud beta emulators pubsub start
export PUBSUB_EMULATOR_HOST="localhost:8085"
```

## Push Worker 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/pubsub/push` | POST | Pub/Sub 消息推送入口 |
| `/metrics` | GET | Prometheus 指标 |
| `/health` | GET | 健康检查 |
| `/ready` | GET | 就绪检查（验证 ES 连接） |

## 配置 Pub/Sub Push 订阅

```bash
gcloud pubsub subscriptions create index-tasks-push \
  --topic=index-tasks \
  --push-endpoint=https://your-worker-url.run.app/pubsub/push \
  --push-auth-service-account=your-sa@project.iam.gserviceaccount.com \
  --ack-deadline=60 \
  --max-delivery-attempts=5 \
  --dead-letter-topic=index-tasks-dlq
```

## 死信队列（DLQ）配置

DLQ 用于处理多次重试后仍失败的消息，避免消息丢失。

### 创建 DLQ Topic 和订阅

```bash
# 创建死信 topic
gcloud pubsub topics create index-tasks-dlq

# 创建死信订阅（用于人工排查）
gcloud pubsub subscriptions create index-tasks-dlq-sub \
  --topic=index-tasks-dlq \
  --ack-deadline=600
```

### 配置主订阅的 DLQ

```bash
# 为现有订阅添加 DLQ 配置
gcloud pubsub subscriptions update index-tasks-sub \
  --dead-letter-topic=index-tasks-dlq \
  --max-delivery-attempts=5

# 授权 Pub/Sub 服务账号发布到 DLQ
gcloud pubsub topics add-iam-policy-binding index-tasks-dlq \
  --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

### DLQ 消息排查

```bash
# 拉取 DLQ 消息查看
gcloud pubsub subscriptions pull index-tasks-dlq-sub --limit=10 --auto-ack=false

# 查看消息详情（包含失败原因）
gcloud pubsub subscriptions pull index-tasks-dlq-sub --format=json
```

## 监控集成（Prometheus + Grafana）

### 指标列表

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `npc_memory_cache_hits_total` | Counter | 缓存命中次数 |
| `npc_memory_cache_misses_total` | Counter | 缓存未命中次数 |
| `npc_memory_embedding_latency_seconds` | Histogram | Embedding 生成延迟 |
| `npc_memory_embedding_requests_total` | Counter | Embedding 请求次数（按状态） |
| `npc_memory_worker_messages_pulled_total` | Counter | 拉取消息总数 |
| `npc_memory_worker_messages_processed_total` | Counter | 处理消息总数（按状态） |
| `npc_memory_worker_bulk_latency_seconds` | Histogram | ES bulk 写入延迟 |

### Prometheus 配置示例

```yaml
scrape_configs:
  - job_name: 'npc-memory-worker'
    static_configs:
      - targets: ['localhost:8080']  # Worker /metrics
    # 或 Cloud Run 服务
    # - targets: ['worker.run.app']
```

### 常用告警规则

```yaml
groups:
  - name: npc-memory
    rules:
      - alert: HighEmbeddingLatency
        expr: histogram_quantile(0.95, npc_memory_embedding_latency_seconds_bucket) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Embedding 延迟过高"

      - alert: HighErrorRate
        expr: rate(npc_memory_worker_messages_processed_total{status="error"}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Worker 错误率过高"
```

## Cloud Run 部署 (新加坡 asia-southeast1)

建议部署到与 Elasticsearch 同区域以减少延迟。

### 1. 前置准备

```bash
gcloud config set run/region asia-southeast1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com
```

### 2. 创建 Secrets

```bash
echo -n "https://your-es-host:443" | gcloud secrets create es-url --data-file=- --replication-policy="automatic"
echo -n "your-es-api-key" | gcloud secrets create es-api-key --data-file=- --replication-policy="automatic"
echo -n "your-modelscope-api-key" | gcloud secrets create modelscope-api-key --data-file=- --replication-policy="automatic"

# 授权访问
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")
for secret in es-url es-api-key modelscope-api-key; do
  gcloud secrets add-iam-policy-binding $secret \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" --quiet
done
```

### 3. 部署 Push Worker

```bash
gcloud run deploy npc-memory-worker \
  --source . \
  --region asia-southeast1 \
  --set-env-vars "PUBSUB_PROJECT_ID=$(gcloud config get-value project),MAX_INFLIGHT_TASKS=4" \
  --set-secrets "ES_URL=es-url:latest,ES_API_KEY=es-api-key:latest,MODELSCOPE_API_KEY=modelscope-api-key:latest" \
  --cpu 2 \
  --memory 4Gi \
  --timeout 60s \
  --concurrency 4 \
  --min-instances 0 \
  --max-instances 10 \
  --allow-unauthenticated
```

### 关键参数说明

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `min-instances` | 0 | 空闲时缩容到零，节省成本 |
| `max-instances` | 10 | 扩容上限，防止过度扩容 |
| `concurrency` | 4 | 单实例并发数，与 MAX_INFLIGHT_TASKS 一致 |
| `timeout` | 60s | 单次请求超时，含 embedding + ES 写入 |

### 自动伸缩机制

1. **空闲缩零**：无请求时缩容到 0 实例
2. **按需扩容**：请求队列积压时自动增加实例
3. **Backpressure**：Worker 满载返回 429，Pub/Sub 暂缓推送
4. **平滑扩容**：Cloud Run 根据请求延迟和队列深度决定扩容速度

### 注意事项

- Elastic Cloud Serverless 不支持 `routing` 参数（`ES_ROUTING_ENABLED=false`）
- `concurrency` 应与 `MAX_INFLIGHT_TASKS` 保持一致，避免资源浪费
