# 异步索引构建指南

本文档说明如何使用新增的异步索引构建功能（Pub/Sub + Worker + 本地 ES）。

## 架构概览

```
写入入口 (add_memory)
    │
    ├─► [同步模式] 直接写入 ES
    │
    └─► [异步模式] 发布到 Pub/Sub
            │
            └─► Worker 拉取任务
                    │
                    ├─► 批量 Embedding
                    ├─► 批量写入 ES
                    └─► Ack 消息
```

## 环境变量配置

### 必需配置

```bash
# Pub/Sub 配置
export PUBSUB_PROJECT_ID="your-gcp-project-id"
export PUBSUB_TOPIC="index-tasks"
export PUBSUB_SUBSCRIPTION="index-tasks-sub"

# Elasticsearch 配置
export ES_URL="http://localhost:9200"

# 异步索引开关（默认关闭）
export INDEX_ASYNC_ENABLED="false"
```

### 可选配置

```bash
# GCP 认证（如果使用 service account）
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

## 快速开始

### 1. 启动本地 Elasticsearch

```bash
docker-compose up -d
```

验证 ES 运行：
```bash
curl http://localhost:9200
```

### 2. 初始化索引

```bash
python examples/init_es.py
```

### 3. 启动 Worker（在独立终端）

```bash
python examples/run_worker.py
```

Worker 会持续运行，拉取并处理索引任务。

### 4. 发布测试任务

```bash
# 确保设置了异步模式
export INDEX_ASYNC_ENABLED="true"

# 发布示例任务
python examples/publish_task.py
```

### 5. 观察 Worker 日志

Worker 终端会显示：
```
Batch complete: {'pulled': 3, 'processed': 3, 'errors': 0}
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

### Worker 参数

```python
worker.run_loop(
    max_messages=50,  # 每次拉取消息数
    batch_size=100    # ES bulk 批量大小
)
```

### 横向扩展

可以启动多个 Worker 实例：
```bash
# Terminal 1
python examples/run_worker.py

# Terminal 2
python examples/run_worker.py
```

多个 Worker 会并行消费同一个 subscription。

## 回滚到同步模式

只需设置：
```bash
export INDEX_ASYNC_ENABLED="false"
```

或者不传入 `pubsub_publisher` 参数，系统自动使用同步写入。

## 常见问题

### Q: Worker 没有拉取到消息？

A: 检查：
1. `PUBSUB_PROJECT_ID` 和 `PUBSUB_SUBSCRIPTION` 是否正确
2. GCP 认证是否配置
3. Pub/Sub 订阅是否存在

### Q: 如何查看 Pub/Sub 消息堆积？

A: 使用 GCP Console 或 gcloud CLI：
```bash
gcloud pubsub subscriptions describe index-tasks-sub
```

### Q: 本地开发如何测试 Pub/Sub？

A: 可以使用 Pub/Sub Emulator：
```bash
gcloud beta emulators pubsub start

# 设置环境变量
export PUBSUB_EMULATOR_HOST="localhost:8085"
```

## Push 模式（推荐用于 Cloud Run）

除了 Pull 模式，系统现在支持 Push 模式，更适合 Cloud Run 等无服务器环境。

### 启动 Push Worker

```bash
# 方式1: 命令行参数
python examples/run_worker.py --push

# 方式2: 环境变量
export WORKER_MODE="push"
python examples/run_worker.py
```

### Push Worker 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/pubsub/push` | POST | Pub/Sub 消息推送入口 |
| `/metrics` | GET | Prometheus 指标 |
| `/health` | GET | 健康检查 |
| `/ready` | GET | 就绪检查（验证 ES 连接） |

### 配置 Pub/Sub Push 订阅

```bash
# 创建 push 订阅（指向 Cloud Run 服务）
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
      - targets: ['localhost:8000']  # Pull 模式
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

## Cloud Run 部署 (香港 asia-east2)

### 1. 前置准备

```bash
# 设置默认 region
gcloud config set run/region asia-east2

# 启用必要 API
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com
```

### 2. 创建 Secrets

```bash
# ES URL
echo -n "https://your-es-host:443" | gcloud secrets create es-url --data-file=- --replication-policy="automatic"

# ES API Key (用于 Elastic Cloud 认证)
echo -n "your-es-api-key" | gcloud secrets create es-api-key --data-file=- --replication-policy="automatic"

# ModelScope API Key
echo -n "your-modelscope-api-key" | gcloud secrets create modelscope-api-key --data-file=- --replication-policy="automatic"

# 授权 Cloud Run 服务账号访问 Secrets
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
  --region asia-east2 \
  --set-env-vars "WORKER_MODE=push,PUBSUB_PROJECT_ID=$(gcloud config get-value project)" \
  --set-secrets "ES_URL=es-url:latest,ES_API_KEY=es-api-key:latest,MODELSCOPE_API_KEY=modelscope-api-key:latest" \
  --cpu 2 \
  --memory 4Gi \
  --timeout 60s \
  --concurrency 10 \
  --max-instances 10 \
  --allow-unauthenticated
```

### 环境变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| `ES_URL` | Elasticsearch 地址 | `https://es.example.com:443` |
| `ES_API_KEY` | Elastic Cloud API Key | (从 Secret Manager 注入) |
| `MODELSCOPE_API_KEY` | ModelScope API 密钥 | (从 Secret Manager 注入) |
| `INDEX_VECTOR_DIMS` | 向量维度 | `1024` |
| `WORKER_MODE` | 工作模式 | `push` |

### 注意事项

- Elastic Cloud Serverless 不支持 `routing` 参数，代码中已移除
- 使用 `ES_API_KEY` 进行 Elastic Cloud 认证，而非 URL 中嵌入密码

### 自动伸缩说明

- Push 模式天然支持按请求量自动扩缩容
- `min-instances=0` 允许缩容到零（省成本）
- `max-instances=10` 限制最大实例数
- `concurrency=10` 每个实例最多处理 10 个并发请求

### Pull 模式不推荐用于 Cloud Run

Pull 模式需要常驻进程轮询，在 Cloud Run 上：
- 无法缩容到零
- 空闲时持续计费
- 建议改用 Push 模式或 GKE

## 模式对比

| 特性 | Pull 模式 | Push 模式 |
|------|-----------|-----------|
| 适用场景 | 本地开发、GKE | Cloud Run、无服务器 |
| 扩缩容 | 手动/HPA | 自动（按请求） |
| 空闲成本 | 持续计费 | 可缩容到零 |
| 批量处理 | 支持 | 单条处理 |
| 复杂度 | 较低 | 需配置 Push 订阅 |
