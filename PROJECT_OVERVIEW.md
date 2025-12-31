# 项目总览

## 目录结构

```
npc-memory-rag/
│
├── src/                          # 源代码
│   ├── __init__.py              # 包初始化
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
│   │   ├── pubsub_client.py     # Pub/Sub 发布订阅封装
│   │   ├── worker.py            # Pull 模式 Worker
│   │   └── push_app.py          # Push 模式 FastAPI 应用
│   │
│   ├── memory_service.py         # Facade 兼容层 + Redis 缓存
│   ├── es_client.py              # ES 客户端工具 + 索引迁移
│   └── metrics.py                # Prometheus 指标定义
│
├── examples/                     # 示例脚本
│   ├── init_es.py               # 初始化 ES 索引
│   ├── publish_task.py          # 发布任务示例
│   ├── run_worker.py            # 运行 Worker（pull/push）
│   └── rollover_index.py        # 索引迁移工具
│
├── demo.py                       # 内存算法演示（无依赖）
├── docker-compose.yml            # ES + Redis + Prometheus
├── prometheus.yml                # Prometheus 配置
├── requirements.txt              # 依赖清单
├── verify_structure.py           # 结构验证脚本
│
├── README.md                     # 项目说明
├── ASYNC_INDEXING.md            # 异步索引指南
├── REFACTORING_SUMMARY.md       # 重构总结
├── CLAUDE.md                    # Claude Code 指引
└── PROJECT_OVERVIEW.md          # 本文件
```

## 模块说明

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
- `PubSubSubscriber`: 订阅消费
- Ack/Nack 封装

#### worker.py (200 行)
- `IndexingWorker`: Pull 模式处理器
- 批量 embedding + Bulk ES 写入
- 幂等性保证（task_id 作为 _id）
- 改进的 ack 策略（全成功才 ack）
- Prometheus 指标埋点

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

### 异步写入流程（Pull 模式）

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
IndexingWorker.pull()
    ↓
批量 Embedding
    ↓
Bulk 写入 ES
    ↓
Ack 消息
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
返回 2xx (ack) 或 5xx (nack)
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
| `WORKER_MODE` | pull | pull 或 push |
| `PORT` | 8080 | Push 模式端口 |
| `METRICS_PORT` | 8000 | 指标端口 |

## 依赖关系

```
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

indexing/worker.py
    ├─► indexing/pubsub_client.py
    ├─► indexing/tasks.py
    ├─► memory/models.py
    ├─► memory/embedding.py
    └─► metrics.py

indexing/push_app.py
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

### 3. Pull vs Push 模式？
- **Pull**：Worker 控制消费速率，适合 GKE
- **Push**：HTTP 端点，适合 Cloud Run 自动伸缩

### 4. 如何保证幂等性？
- 使用 `task_id` 作为 ES `_id`
- 重复消息覆盖，不产生重复记录
- 消息重试安全

### 5. 为什么改进 ack 策略？
- 原策略：部分成功也 ack
- 新策略：全部成功才 ack，否则全部 nack
- 配合 DLQ 处理失败消息

## 性能考虑

### 批量处理
- Worker 批量 pull (max_messages=10)
- 批量 embedding (减少模型调用)
- Bulk ES 写入 (batch_size=50)

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
- 真实 Embedding（Qwen3）支持
- Redis 查询结果缓存
- Prometheus 监控指标
- Pull/Push 双模式 Worker
- DLQ 死信队列支持
- Cloud Run 部署就绪

符合最小化改动、不过度设计、保持简洁的原则。
