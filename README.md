# NPC Memory RAG 系统

基于 Elasticsearch 的游戏 NPC 记忆检索增强生成(RAG)系统，支持混合检索、异步索引和 Cloud Run 部署。

## 项目结构

```
npc-memory-rag/
├── src/
│   ├── memory/              # 核心记忆模块
│   │   ├── models.py        # 数据模型
│   │   ├── embedding.py     # Embedding 服务（Qwen3/stub）
│   │   ├── es_schema.py     # ES 索引配置
│   │   ├── search.py        # 混合检索
│   │   └── write.py         # 写入操作
│   ├── indexing/            # 异步索引模块
│   │   ├── tasks.py         # 索引任务定义
│   │   ├── pubsub_client.py # Pub/Sub 封装
│   │   ├── worker.py        # Pull 模式 Worker
│   │   └── push_app.py      # Push 模式 FastAPI
│   ├── memory_service.py    # Facade 兼容层
│   ├── es_client.py         # ES 客户端工具
│   └── metrics.py           # Prometheus 指标
├── examples/                # 示例脚本
│   ├── init_es.py          # 初始化 ES 索引
│   ├── publish_task.py     # 发布任务示例
│   ├── run_worker.py       # 运行 Worker（pull/push）
│   └── rollover_index.py   # 索引迁移工具
├── demo.py                  # 算法演示（无依赖）
├── docker-compose.yml       # ES + Redis + Prometheus
└── ASYNC_INDEXING.md       # 异步索引指南
```

## 核心特性

### 1. 混合检索（BM25 + Vector + RRF）

- BM25 关键词搜索 + 向量语义搜索
- RRF 融合排序算法
- 记忆衰减机制（模拟遗忘曲线）

### 2. 真实 Embedding

- 集成 ModelScope Qwen3-Embedding-8B
- 支持自动回退 stub（无需配置即可运行）
- 批量 embedding 优化吞吐

### 3. 异步索引（Pub/Sub）

- **Pull 模式**：Worker 轮询消费，适合 GKE
- **Push 模式**：FastAPI HTTP 端点，适合 Cloud Run
- 死信队列（DLQ）支持

### 4. 缓存与监控

- Redis 查询结果缓存
- Prometheus 指标采集
- 支持 Grafana 可视化

## 快速开始

### 1. 启动开发环境

```bash
# 完整环境（ES + Redis + Prometheus）
docker-compose up -d

# 仅 ES（轻量开发）
docker-compose up -d es-coordinator kibana
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 初始化索引

```bash
python examples/init_es.py
```

### 4. 运行演示

```bash
# 无依赖演示（自动使用 stub embedding）
python demo.py
```

### 5. 同步模式使用

```python
from src.es_client import create_es_client
from src.memory import EmbeddingService, Memory, MemoryType
from src.memory_service import NPCMemoryService, create_redis_cache

# 初始化
es = create_es_client()
embedder = EmbeddingService()
cache = create_redis_cache()  # 可选

service = NPCMemoryService(es, embedder, cache_client=cache)

# 写入记忆
memory = Memory(
    id="mem_001",
    player_id="player_123",
    npc_id="npc_456",
    memory_type=MemoryType.DIALOGUE,
    content="玩家与NPC的对话内容",
    importance=0.7
)
service.add_memory(memory)

# 检索记忆
results = service.search_memories(
    player_id="player_123",
    npc_id="npc_456",
    query="对话",
    top_k=5
)
```

### 6. 异步模式（Worker）

```bash
# Pull 模式
python examples/run_worker.py

# Push 模式（FastAPI）
python examples/run_worker.py --push
```

详见 [ASYNC_INDEXING.md](ASYNC_INDEXING.md)

## 环境变量

### 核心配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_URL` | http://localhost:9200 | ES 地址 |
| `INDEX_ASYNC_ENABLED` | false | 异步索引开关 |

### Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_PROVIDER` | modelscope | modelscope 或 stub |
| `MODELSCOPE_API_KEY` | - | ModelScope 密钥 |
| `EMBEDDING_MODEL` | Qwen/Qwen3-Embedding-8B | 模型名 |
| `INDEX_VECTOR_DIMS` | 1024 | 向量维度 |

### 缓存配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_URL` | - | Redis 地址 |
| `CACHE_TTL_SECONDS` | 300 | 缓存过期时间 |

### Worker 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WORKER_MODE` | pull | pull 或 push |
| `PORT` | 8080 | Push 模式端口 |
| `METRICS_PORT` | 8000 | 指标端口 |

## Cloud Run 部署

```bash
gcloud run deploy npc-memory-worker \
  --source . \
  --region us-central1 \
  --set-env-vars WORKER_MODE=push \
  --set-secrets MODELSCOPE_API_KEY=modelscope-key:latest \
  --min-instances 0 \
  --max-instances 10
```

详见 [ASYNC_INDEXING.md](ASYNC_INDEXING.md) 中的部署章节。

## 技术栈

- **Elasticsearch 8.11**: 混合检索、向量索引
- **ModelScope Qwen3**: Embedding 生成
- **Google Cloud Pub/Sub**: 异步任务队列
- **Redis**: 查询缓存
- **FastAPI**: Push Worker
- **Prometheus**: 监控指标

## 已完成功能

- [x] 模块化设计（memory/indexing）
- [x] 混合检索（BM25 + Vector + RRF）
- [x] 真实 Embedding（Qwen3）
- [x] 同步/异步写入模式
- [x] Redis 查询缓存
- [x] Prometheus 监控
- [x] Push 模式 Worker
- [x] DLQ 支持
- [x] Cloud Run 部署指南

## 文档

- [异步索引指南](ASYNC_INDEXING.md) - Pull/Push 模式、DLQ、Cloud Run
- [项目总览](PROJECT_OVERVIEW.md) - 架构设计、数据流
- [重构记录](REFACTORING_SUMMARY.md) - 模块化过程

## License

MIT
