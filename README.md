# NPC Memory RAG 系统

基于 Elasticsearch 的游戏 NPC 记忆检索增强生成(RAG)系统，支持混合检索、异步索引和 Cloud Run 部署。

## 项目结构

```
npc-memory-rag/
├── src/
│   ├── api/                 # REST API 服务层
│   │   ├── app.py           # FastAPI 主应用（API 入口）
│   │   ├── schemas.py       # Pydantic 数据模型
│   │   └── dependencies.py  # 依赖注入
│   ├── memory/              # 核心记忆模块
│   │   ├── models.py        # 数据模型（Memory、MemoryContext）
│   │   ├── embedding.py     # Embedding 服务（Qwen3）
│   │   ├── es_schema.py     # ES 索引配置
│   │   ├── search.py        # 混合检索（BM25+Vector+RRF）
│   │   └── write.py         # 写入操作
│   ├── indexing/            # 异步索引模块
│   │   ├── tasks.py         # 索引任务定义
│   │   ├── pubsub_client.py # Pub/Sub 封装
│   │   └── push_app.py      # Push Worker（Worker 入口）
│   ├── memory_service.py    # Facade 兼容层
│   ├── es_client.py         # ES 客户端工具
│   └── metrics.py           # Prometheus 指标
├── examples/                # 示例脚本
│   └── benchmark.py         # 性能基准测试
├── Dockerfile               # 容器化部署
└── docker-compose.yml       # ES + Redis + Prometheus
```

## 系统架构

```mermaid
flowchart TB
    subgraph Client["客户端"]
        GameClient["游戏客户端"]
    end

    subgraph API["API Service (FastAPI)"]
        APIApp["src/api/app.py"]
        Schemas["schemas.py"]
        Deps["dependencies.py"]
    end

    subgraph Core["Memory Core"]
        Service["memory_service.py<br/>Facade"]
        Search["search.py<br/>BM25+Vector+RRF"]
        Write["write.py"]
        Embed["embedding.py<br/>Qwen3"]
        Models["models.py"]
    end

    subgraph Worker["Worker Service (FastAPI)"]
        PushApp["src/indexing/push_app.py"]
        Tasks["tasks.py"]
    end

    subgraph Infra["Infrastructure"]
        ES["Elasticsearch<br/>混合检索"]
        Redis["Redis<br/>缓存 + Reply"]
        PubSub["Pub/Sub<br/>任务队列"]
    end

    GameClient -->|REST| APIApp
    APIApp --> Service
    Service --> Search
    Service --> Write
    Search --> Embed
    Write --> Embed
    Search --> ES
    Write -->|同步| ES
    Write -->|异步| PubSub
    PubSub --> PushApp
    PushApp --> Embed
    PushApp --> ES
    PushApp -->|Reply| Redis
    APIApp -->|Wait| Redis
    Service --> Redis
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

- **Push Worker**：FastAPI HTTP 端点（`POST /pubsub/push`），适合 Cloud Run 自动伸缩
- **Request-Reply（同步返回）**：API 入队后通过 Redis 阻塞等待 worker 结果，然后在同一条 HTTP 请求里返回给客户端
- 死信队列（DLQ）支持

### 4. REST API 服务

- 独立的 FastAPI 服务，支持 OpenAPI 文档
- `POST /memories` - 入队并同步等待 worker 完成后返回（request-reply）
- `GET /search` - 入队并同步等待 worker 查询后返回（request-reply）
- `GET /context` - LLM 上下文准备

### 5. 缓存与监控

- Redis 查询结果缓存
- Prometheus 指标采集
- 支持 Grafana 可视化

## 快速开始

### 1. 启动开发环境

```bash
# 完整环境（ES + Redis + Prometheus）
docker-compose up -d

# 轻量开发（推荐）
docker-compose up -d es-coordinator kibana redis
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 初始化索引

```bash
python -c "from src.es_client import create_es_client, initialize_index; initialize_index(create_es_client())"
```

### 4. 启动服务

```bash
# 启动 API 服务
uvicorn src.api.app:app --host 0.0.0.0 --port 8000

# 启动 Worker 服务（异步模式需要，另开终端）
uvicorn src.indexing.push_app:app --host 0.0.0.0 --port 8080
```

启动后访问 http://localhost:8000/docs 查看 OpenAPI 文档。

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

异步模式需要配置 Pub/Sub 和 Redis：

```bash
# 设置环境变量
export INDEX_ASYNC_ENABLED=true
export REDIS_URL=redis://localhost:6379
export PUBSUB_PROJECT_ID=your-project-id
export PUBSUB_TOPIC=npc-memory-tasks

# 启动 Worker
uvicorn src.indexing.push_app:app --host 0.0.0.0 --port 8080
```

详见 [ASYNC_INDEXING.md](ASYNC_INDEXING.md)

## 环境变量

### 核心配置

| 变量                    | 默认值                | 说明                  |
| ----------------------- | --------------------- | --------------------- |
| `ES_URL`              | http://localhost:9200 | ES 地址               |
| `ES_API_KEY`          | -                     | Elastic Cloud API Key |
| `INDEX_ASYNC_ENABLED` | false                 | 异步索引开关          |

### Embedding 配置

| 变量                   | 默认值                  | 说明               |
| ---------------------- | ----------------------- | ------------------ |
| `EMBEDDING_PROVIDER` | modelscope              | modelscope 或 stub |
| `MODELSCOPE_API_KEY` | -                       | ModelScope 密钥    |
| `EMBEDDING_MODEL`    | Qwen/Qwen3-Embedding-8B | 模型名             |
| `INDEX_VECTOR_DIMS`  | 1024                    | 向量维度           |

### 缓存配置

| 变量                  | 默认值 | 说明                                            |
| --------------------- | ------ | ----------------------------------------------- |
| `REDIS_URL`         | -      | Redis 地址（查询缓存 + request-reply 回传通道） |
| `CACHE_TTL_SECONDS` | 300    | 缓存过期时间                                    |

### Worker 配置

| 变量                        | 默认值 | 说明                                 |
| --------------------------- | ------ | ------------------------------------ |
| `PORT`                    | 8080   | Push 模式端口                        |
| `REQUEST_TIMEOUT_SECONDS` | 25     | API 等待 worker 返回结果的超时（秒） |
| `REPLY_TTL_SECONDS`       | 60     | Redis 回传结果的 TTL（秒）           |

## Cloud Run 部署 (新加坡 asia-southeast1)

### 已部署服务

| 服务           | URL                                                            | 说明         |
| -------------- | -------------------------------------------------------------- | ------------ |
| API Service    | https://npc-memory-api-xxxxxxxxxxxx.asia-southeast1.run.app    | REST API     |
| Worker Service | https://npc-memory-worker-xxxxxxxxxxxx.asia-southeast1.run.app | 异步索引处理 |

### API 使用示例

```bash
# 写入记忆
curl -X POST https://npc-memory-api-xxxxxxxxxxxx.asia-southeast1.run.app/memories \
  -H "Content-Type: application/json" \
  -d '{"player_id":"player_1","npc_id":"npc_1","memory_type":"dialogue","content":"测试内容","importance":0.8}'

# 搜索记忆
curl "https://npc-memory-api-xxxxxxxxxxxx.asia-southeast1.run.app/search?player_id=player_1&npc_id=npc_1&query=测试"

# 查看 OpenAPI 文档
open https://npc-memory-api-xxxxxxxxxxxx.asia-southeast1.run.app/docs
```

详见 [CLAUDE.md](CLAUDE.md) 和 [ASYNC_INDEXING.md](ASYNC_INDEXING.md) 中的部署章节。

## 技术栈

- **Elasticsearch 8.11**: 混合检索、向量索引
- **ModelScope Qwen3**: Embedding 生成
- **Google Cloud Pub/Sub**: 异步任务队列
- **Redis**: 查询缓存
- **FastAPI**: Push Worker
- **Prometheus**: 监控指标

## 已完成功能

- [X] 模块化设计（api/memory/indexing）
- [X] REST API 服务（FastAPI + OpenAPI）
- [X] 混合检索（BM25 + Vector + RRF）
- [X] 真实 Embedding（Qwen3）
- [X] 同步/异步写入模式
- [X] Redis 查询缓存
- [X] Prometheus 监控
- [X] Push 模式 Worker
- [X] DLQ 支持
- [X] Cloud Run 双服务部署（API + Worker）
