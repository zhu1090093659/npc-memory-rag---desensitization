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

## 下一步扩展

1. **Push 模式**：修改 Worker 为 HTTP 端点，支持 Pub/Sub push
2. **Cloud Run 部署**：将 Worker 部署到 Cloud Run，自动横向扩展
3. **监控集成**：接入 Prometheus/Grafana 监控
4. **死信队列**：配置 DLQ 处理失败消息
