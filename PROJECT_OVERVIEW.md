# 项目总览

## 目录结构

```
npc-memory-rag/
│
├── src/                          # 源代码
│   ├── __init__.py              # 包初始化
│   │
│   ├── api/                      # REST API 服务层
│   │   ├── __init__.py          # 导出 app
│   │   ├── app.py               # FastAPI 主应用
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   └── dependencies.py      # 依赖注入（单例模式）
│   │
│   ├── memory/                   # 核心记忆模块
│   │   ├── __init__.py          # 导出所有记忆组件
│   │   ├── models.py            # 数据模型 (Memory, MemoryType, MemoryContext)
│   │   ├── embedding.py         # Embedding 服务（Qwen3/stub）
│   │   ├── es_schema.py         # ES 索引配置与创建
│   │   ├── search.py            # 混合检索 (BM25 + Vector + RRF)
│   │   └── write.py             # 写入操作 (同步/异步)
│   │
│   ├── indexing/                 # 异步索引模块
│   │   ├── __init__.py          # 导出索引组件
│   │   ├── tasks.py             # IndexTask 定义与序列化
│   │   ├── pubsub_client.py     # Pub/Sub 发布封装
│   │   └── push_app.py          # Push Worker（Pub/Sub HTTP 推送入口）
│   │
│   ├── memory_service.py         # Facade 兼容层 + Redis 缓存
│   ├── es_client.py              # ES 客户端工具 + 索引迁移
│   └── metrics.py                # Prometheus 指标定义
│
├── examples/                     # 示例脚本
├── demo.py                       # 内存算法演示（无依赖）
├── Dockerfile                    # 容器化部署
├── docker-compose.yml            # ES + Redis + Prometheus
├── prometheus.yml                # Prometheus 配置
├── requirements.txt              # 依赖清单
│
├── README.md                     # 项目说明
├── ASYNC_INDEXING.md            # 异步索引指南
├── CLAUDE.md                    # Claude Code 指引
└── PROJECT_OVERVIEW.md          # 本文件
```

## 模块说明

### 0. src/api - REST API 服务层

#### app.py (150 行)
- FastAPI 主应用
- `POST /memories`: 入队并同步等待 worker 完成后返回（request-reply）
- `GET /search`: 入队并同步等待 worker 查询后返回（request-reply）
- `GET /context`: LLM 上下文准备
- `GET /health/ready/metrics`: 健康检查和监控

#### schemas.py (80 行)
- `MemoryCreateRequest`: 写入请求模型
- `MemoryCreateResponse`: 写入响应（task_id + memory_id）
- `MemoryResponse`: 单条记忆响应
- `SearchResponse`: 搜索结果响应

#### dependencies.py (50 行)
- 依赖注入，单例模式
- `get_memory_service()`: NPCMemoryService
- `get_publisher()`: PubSubPublisher

### 1. src/memory - 核心记忆模块

#### models.py (60 行)
- `MemoryType`: 记忆类型枚举
- `Memory`: 记忆数据类
- `MemoryContext`: LLM 上下文

#### embedding.py (160 行)
- `EmbeddingService`: Embedding 服务接口
- 支持 ModelScope Qwen3-Embedding-8B
- 自动回退 stub（无 API Key 时）
- 批量 embedding + 内存缓存
- 超时重试 + 指标采集

#### es_schema.py (120 行)
- `INDEX_SETTINGS`: ES 索引配置
- `INDEX_ALIAS`: 索引别名
- `INDEX_VECTOR_DIMS`: 可配置向量维度
- `get_index_settings()`: 动态配置生成
- `create_index_if_not_exists()`: 索引创建

#### search.py (220 行)
- `MemorySearcher`: 混合检索类
- BM25 关键词搜索
- Vector 语义搜索
- RRF 融合算法
- 记忆衰减机制

#### write.py (85 行)
- `MemoryWriter`: 写入操作类
- 同步写入 ES
- 异步发布到 Pub/Sub
- 开关控制

### 2. src/indexing - 异步索引模块

#### tasks.py (85 行)
- `IndexTask`: 索引任务数据类
- JSON 序列化/反序列化
- 工厂方法

#### pubsub_client.py (120 行)
- `PubSubPublisher`: 发布任务
- （仅保留 Publisher；消费由 Pub/Sub Push 触发 Worker）

#### push_app.py (130 行)
- FastAPI 应用
- `POST /pubsub/push`: Pub/Sub 推送入口
- `GET /metrics`: Prometheus 指标
- `GET /health`: 健康检查
- `GET /ready`: 就绪检查

### 3. Facade 层

#### memory_service.py (200 行)
- `NPCMemoryService`: Facade 类
- `RedisCacheAdapter`: Redis 缓存适配器
- `create_redis_cache()`: 缓存工厂
- 组合各模块功能
- 保持向后兼容

#### es_client.py (120 行)
- `create_es_client()`: 创建 ES 客户端
- `initialize_index()`: 索引初始化
- `create_index_with_rollover()`: 索引迁移
- `check_es_health()`: 健康检查

### 4. 监控模块

#### metrics.py (120 行)
- Prometheus 指标定义
- 缓存命中/未命中计数
- Embedding 延迟直方图
- Worker 处理统计
- Bulk 写入延迟

## 数据流

### 同步写入流程

```
Memory对象
    ↓
MemoryWriter.add_memory()
    ↓
生成 Embedding（Qwen3 或 stub）
    ↓
ES.index()
    ↓
返回 memory_id
```

### 异步写入流程（Push 模式）

```
Memory对象
    ↓
MemoryWriter.add_memory(async_index=True)
    ↓
转换为 IndexTask
    ↓
PubSubPublisher.publish()
    ↓
[Pub/Sub Topic]
    ↓
HTTP POST → push_app.py
    ↓
process_single_task()
    ↓
Embedding + ES.index()
    ↓
写入 Redis reply:{task_id}
    ↓
API BRPOP 等待结果并返回给客户端
```

### 检索流程

```
查询请求
    ↓
检查 Redis 缓存 → 命中则返回
    ↓
MemorySearcher.search_memories()
    ↓
并行执行:
  ├─► BM25 搜索
  └─► Vector 搜索
    ↓
RRF 融合排序
    ↓
记忆衰减
    ↓
写入 Redis 缓存
    ↓
返回 Memory 列表
```

## 配置管理

所有配置通过环境变量：

### 核心配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ES_URL` | http://localhost:9200 | ES 连接地址 |
| `ES_API_KEY` | - | Elastic Cloud API Key |
| `INDEX_ASYNC_ENABLED` | false | 异步索引开关 |
| `PUBSUB_PROJECT_ID` | - | GCP 项目 ID |
| `PUBSUB_TOPIC` | index-tasks | Pub/Sub Topic |
| `PUBSUB_SUBSCRIPTION` | index-tasks-sub | Pub/Sub 订阅 |

### Embedding 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EMBEDDING_PROVIDER` | modelscope | modelscope 或 stub |
| `MODELSCOPE_API_KEY` | - | API 密钥 |
| `EMBEDDING_MODEL` | Qwen/Qwen3-Embedding-8B | 模型名 |
| `INDEX_VECTOR_DIMS` | 1024 | 向量维度 |
| `EMBEDDING_CACHE_ENABLED` | false | 内存缓存开关 |

### Redis 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `REDIS_URL` | - | Redis 连接地址 |
| `CACHE_TTL_SECONDS` | 300 | 缓存 TTL |

### Worker 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | 8080 | Push 模式端口 |
| `REQUEST_TIMEOUT_SECONDS` | 25 | API 等待 worker 返回结果的超时（秒） |
| `REPLY_TTL_SECONDS` | 60 | Redis 回传结果 TTL（秒） |

## 依赖关系

```
api/app.py (REST API)
    ├─► api/schemas.py
    ├─► api/dependencies.py
    │       ├─► memory_service.py
    │       └─► indexing/pubsub_client.py
    └─► indexing/tasks.py

memory_service.py (Facade)
    ├─► memory/search.py
    │       └─► memory/models.py
    │       └─► memory/embedding.py
    │
    ├─► memory/write.py
    │       ├─► memory/models.py
    │       └─► indexing/tasks.py
    │       └─► indexing/pubsub_client.py
    │
    └─► metrics.py

indexing/push_app.py (Worker)
    ├─► indexing/tasks.py
    ├─► memory/models.py
    ├─► memory/embedding.py
    ├─► es_client.py
    └─► metrics.py

es_client.py
    └─► memory/es_schema.py
```

## 关键设计决策

### 1. 为什么使用 Facade 模式？
- 保持向后兼容，不破坏现有调用
- 统一入口，简化使用
- 便于后续扩展

### 2. 为什么分离同步/异步？
- 开发阶段需要即时反馈
- 生产阶段需要解耦和扩展
- 通过开关灵活切换

### 3. 为什么采用 Push Worker？
- Worker 通过 HTTP 端点接收 Pub/Sub 推送，天然适配 Cloud Run 自动伸缩
- 配合 429 backpressure，满载时让 Pub/Sub 自动重试，避免把实例压垮

### 4. 如何保证幂等性？
- 使用 `task_id` 作为 ES `_id`
- 重复消息覆盖，不产生重复记录
- 消息重试安全

## 性能考虑

### 并发与限流
- `MAX_INFLIGHT_TASKS` 限制单实例同时处理的任务数
- 满载返回 429，触发 Pub/Sub 重试，等待 Cloud Run 扩容

### 缓存优化
- Redis 缓存热门查询
- Embedding 内存缓存（可选）
- 版本前缀支持缓存失效

### 查询优化
- Routing by npc_id (单分片查询)
- 只返回必要字段
- 向量索引 HNSW

### 扩展性
- Worker 可多实例部署
- 无状态设计
- 水平扩展

## 监控指标

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `npc_memory_cache_hits_total` | Counter | 缓存命中 |
| `npc_memory_cache_misses_total` | Counter | 缓存未命中 |
| `npc_memory_embedding_latency_seconds` | Histogram | Embedding 延迟 |
| `npc_memory_embedding_requests_total` | Counter | Embedding 请求 |
| `npc_memory_worker_messages_pulled_total` | Counter | 拉取消息数 |
| `npc_memory_worker_messages_processed_total` | Counter | 处理消息数 |
| `npc_memory_worker_bulk_latency_seconds` | Histogram | Bulk 延迟 |

## 总结

本项目通过模块化设计，实现了：
- REST API 服务（FastAPI + OpenAPI）
- 真实 Embedding（Qwen3）支持
- Redis 查询结果缓存
- Prometheus 监控指标
- Push Worker（Pub/Sub HTTP 推送入口）
- DLQ 死信队列支持
- Cloud Run 双服务部署（API + Worker）

符合最小化改动、不过度设计、保持简洁的原则。

## 已部署服务

| 服务 | URL |
|------|-----|
| API Service | https://npc-memory-api-257652255998.asia-southeast1.run.app |
| Worker Service | https://npc-memory-worker-257652255998.asia-southeast1.run.app |
| OpenAPI 文档 | https://npc-memory-api-257652255998.asia-southeast1.run.app/docs |
