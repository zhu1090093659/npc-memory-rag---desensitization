# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

NPC Memory RAG 系统是一个基于 Elasticsearch 的游戏 NPC 记忆检索增强生成(RAG)系统，支持混合检索(BM25 + Vector + RRF)和异步索引构建。本项目目标是部署到 Google Cloud Run。

## 核心架构

### 三层架构设计

1. **Facade 层** (`src/memory_service.py`)
   - `NPCMemoryService` 作为统一入口，保持向后兼容
   - 组合所有子模块功能
   - 集成可选的 Redis 缓存

2. **核心记忆模块** (`src/memory/`)
   - `models.py`: 数据模型定义(Memory, MemoryType, MemoryContext)
   - `embedding.py`: Embedding 服务接口，支持 ModelScope Qwen3 或 stub 回退
   - `es_schema.py`: Elasticsearch 索引配置(30 分片, HNSW 向量索引, 可配置向量维度)
   - `search.py`: **核心检索逻辑** - BM25 + Vector 并行搜索 + RRF 融合 + 记忆衰减
   - `write.py`: 写入操作，支持同步/异步模式切换

3. **异步索引模块** (`src/indexing/`)
   - `tasks.py`: IndexTask 任务定义与 JSON 序列化
   - `pubsub_client.py`: Google Cloud Pub/Sub 封装(Publisher/Subscriber)
   - `worker.py`: Pull 模式 Worker，批量 embedding + bulk ES 写入，保证幂等性
   - `push_app.py`: Push 模式 FastAPI 应用，支持 Pub/Sub HTTP 推送

4. **监控模块** (`src/metrics.py`)
   - Prometheus 指标定义和采集
   - 支持 pull 模式独立 metrics server 和 push 模式 /metrics 端点

### 数据流

**同步写入**: Memory → MemoryWriter → 生成 Embedding → ES.index()

**异步写入**: Memory → MemoryWriter → IndexTask → Pub/Sub Topic → Worker(批量处理) → Bulk ES 写入

**混合检索**: 查询 → 并行(BM25 + Vector) → RRF 融合 → 记忆衰减 → 返回结果

### 设计模式

- **Facade 模式**: NPCMemoryService 统一接口
- **Strategy 模式**: 同步/异步写入可切换
- **Factory 模式**: IndexTask.create() 工厂方法

### 幂等性保证

Worker 使用 `task_id` 作为 ES 文档 `_id`，重复消息会覆盖而非重复插入，确保消息重试安全。

## 环境变量配置

### 核心配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ES_URL` | http://localhost:9200 | Elasticsearch 连接地址 |
| `INDEX_ASYNC_ENABLED` | false | 异步索引开关 |
| `PUBSUB_PROJECT_ID` | (必需) | GCP 项目 ID |
| `PUBSUB_TOPIC` | index-tasks | Pub/Sub Topic 名称 |
| `PUBSUB_SUBSCRIPTION` | index-tasks-sub | Pub/Sub 订阅名称 |
| `GOOGLE_APPLICATION_CREDENTIALS` | (可选) | GCP Service Account JSON 路径 |

### Embedding 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EMBEDDING_PROVIDER` | modelscope | 提供者: modelscope 或 stub |
| `MODELSCOPE_API_KEY` | (必需) | ModelScope API 密钥 |
| `MODELSCOPE_BASE_URL` | https://api-inference.modelscope.cn/v1 | API 地址 |
| `EMBEDDING_MODEL` | Qwen/Qwen3-Embedding-8B | 模型名称 |
| `INDEX_VECTOR_DIMS` | 1024 | 向量维度 |
| `EMBEDDING_CACHE_ENABLED` | false | 内存缓存开关 |

### Redis 缓存配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `REDIS_URL` | (可选) | Redis 连接地址 |
| `CACHE_TTL_SECONDS` | 300 | 缓存过期时间 |

### Worker 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `WORKER_MODE` | pull | 工作模式: pull 或 push |
| `PORT` | 8080 | Push 模式 HTTP 端口 |
| `METRICS_PORT` | 8000 | Pull 模式指标端口 |

## 常用命令

### 开发调试

```bash
# 安装依赖
pip install -r requirements.txt

# 启动本地 ES 集群 (3 master + 2 hot + 2 warm + 1 coordinator + Kibana)
docker-compose up -d

# 验证 ES 运行
curl http://localhost:9200

# 初始化 ES 索引
python examples/init_es.py

# 运行无依赖的内存算法演示
python demo.py

# 验证项目结构
python verify_structure.py
```

### 异步索引模式

```bash
# Terminal 1: 启动 Worker (持续运行)
export PUBSUB_PROJECT_ID="your-gcp-project-id"
export PUBSUB_TOPIC="index-tasks"
export PUBSUB_SUBSCRIPTION="index-tasks-sub"
python examples/run_worker.py

# Terminal 2: 发布索引任务
export INDEX_ASYNC_ENABLED="true"
python examples/publish_task.py
```

### 同步索引模式 (默认)

```python
from src.es_client import create_es_client
from src.memory import EmbeddingService, Memory, MemoryType
from src.memory_service import NPCMemoryService

es = create_es_client()
embedder = EmbeddingService()
service = NPCMemoryService(es, embedder)

# 直接写入，即刻可查
memory = Memory(...)
service.add_memory(memory)
results = service.search_memories(player_id, npc_id, query)
```

### Cloud Run 部署

```bash
# 使用 gcloud 部署 Worker
gcloud run deploy npc-memory-worker \
  --source . \
  --region us-central1 \
  --set-env-vars PUBSUB_PROJECT_ID=your-project-id \
  --set-env-vars ES_URL=your-es-url \
  --cpu 2 \
  --memory 4Gi \
  --max-instances 10

# 本地已安装 gcloud CLI
gcloud config list
gcloud auth list
```

## 关键技术细节

### RRF 融合算法

`src/memory/search.py` 的 `_rrf_fusion()` 方法实现 Reciprocal Rank Fusion:

```
RRF(doc) = Σ 1 / (k + rank_i(doc))
```

其中 k=60 是平滑参数，rank_i 是文档在第 i 个搜索结果中的排名。这是项目的核心亮点。

### 记忆衰减机制

`src/memory/search.py` 的 `_apply_memory_decay()` 实现基于时间的重要性衰减:

```
decayed_importance = importance × e^(-λ × days)
```

默认 λ=0.02，模拟人类遗忘曲线。

### Elasticsearch 优化

- **30 分片**: 支持高并发写入
- **Routing by npc_id**: 按 NPC 路由到单分片，减少扇出
- **HNSW 向量索引**: `m=16, ef_construction=100` 平衡速度和召回率
- **冷热分离**: 热数据(data_hot)在 SSD，温数据(data_warm)在 HDD
- **ILM 策略**: 按月滚动索引，自动迁移到 warm 层

### Worker 批量处理

`src/indexing/worker.py`:
- 批量 pull (max_messages=10)
- 批量 embedding (减少模型调用)
- Bulk ES 写入 (batch_size=50)
- 错误处理: 解析失败 nack，embedding 失败不 ack

## 测试与验证

```bash
# 结构验证 (不需要安装依赖)
python verify_structure.py

# 算法演示 (不需要 ES 和 Pub/Sub)
python demo.py

# 集成测试 (需要 ES 和 Pub/Sub)
# 1. 启动 ES
docker-compose up -d
# 2. 初始化索引
python examples/init_es.py
# 3. 启动 Worker
python examples/run_worker.py &
# 4. 发布任务
python examples/publish_task.py
# 5. 查看 Kibana
open http://localhost:5601
```

## 模块依赖关系

```
memory_service.py (Facade)
    ├─► memory/search.py
    │       └─► memory/models.py
    │       └─► memory/embedding.py
    │
    └─► memory/write.py
            ├─► memory/models.py
            └─► indexing/tasks.py
            └─► indexing/pubsub_client.py

indexing/worker.py
    ├─► indexing/pubsub_client.py
    ├─► indexing/tasks.py
    ├─► memory/models.py
    └─► memory/embedding.py

es_client.py
    └─► memory/es_schema.py
```

## 代码修改原则

1. **最小化改动**: 优先编辑现有文件，避免创建新文件
2. **保持简洁**: 避免过度设计，每个函数职责单一
3. **圈复杂度控制**: 函数不超过 50 行，类不超过 200 行
4. **设计模式优先**: 使用 Facade/Strategy/Factory 等模式
5. **模块边界**: 不跨模块修改，通过接口协作
6. **包导入**: 所有 import 放在文件头部
7. **注释语言**: 代码注释使用英文，对外文档使用中文

## 重要文件说明

- **PROJECT_OVERVIEW.md**: 完整的项目总览和架构说明
- **ASYNC_INDEXING.md**: 异步索引详细指南，包含配置、使用场景、故障排查
- **REFACTORING_SUMMARY.md**: 记录了从单文件 650 行重构到模块化架构的过程
- **README.md**: 快速开始指南
- **docker-compose.yml**: 完整的 ES 集群配置 (3 master + 2 hot + 2 warm)
- **demo.py**: 无依赖的内存算法演示，可用于面试讲解

## 已完成功能

1. **真实 Embedding**: 已集成 ModelScope Qwen3-Embedding-8B，支持自动回退 stub
2. **Redis 缓存**: 已实现查询结果缓存，支持 TTL 和版本控制
3. **监控集成**: 已集成 Prometheus 指标，支持缓存/embedding/worker 监控
4. **Push 模式**: 已实现 FastAPI Push Worker，支持 Pub/Sub HTTP 推送
5. **死信队列**: 已优化 ack/nack 策略，配合 DLQ 配置指南
6. **Cloud Run 部署**: 已提供完整部署指南和自动伸缩说明

## 下一步优化方向

1. **向量维度迁移**: 使用 rollover 工具切换到更高维度模型
2. **批量 reindex**: 历史数据重新 embedding 迁移工具
3. **Grafana Dashboard**: 预置监控面板模板
4. **负载测试**: 压测脚本和性能基线
