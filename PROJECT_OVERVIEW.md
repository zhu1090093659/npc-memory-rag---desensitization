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
│   │   ├── embedding.py         # Embedding 服务接口
│   │   ├── es_schema.py         # ES 索引配置与创建
│   │   ├── search.py            # 混合检索 (BM25 + Vector + RRF)
│   │   └── write.py             # 写入操作 (同步/异步)
│   │
│   ├── indexing/                 # 异步索引模块
│   │   ├── __init__.py          # 导出索引组件
│   │   ├── tasks.py             # IndexTask 定义与序列化
│   │   ├── pubsub_client.py     # Pub/Sub 发布订阅封装
│   │   └── worker.py            # Worker 消费处理器
│   │
│   ├── memory_service.py         # Facade 兼容层
│   └── es_client.py              # ES 客户端工具
│
├── examples/                     # 示例脚本
│   ├── init_es.py               # 初始化 ES 索引
│   ├── publish_task.py          # 发布任务示例
│   └── run_worker.py            # 运行 Worker
│
├── demo.py                       # 内存算法演示
├── docker-compose.yml            # ES 集群配置
├── requirements.txt              # 依赖清单
├── verify_structure.py           # 结构验证脚本
│
├── README.md                     # 项目说明
├── ASYNC_INDEXING.md            # 异步索引指南
├── REFACTORING_SUMMARY.md       # 重构总结
└── PROJECT_OVERVIEW.md          # 本文件
```

## 模块说明

### 1. src/memory - 核心记忆模块

#### models.py (60 行)
- `MemoryType`: 记忆类型枚举
- `Memory`: 记忆数据类
- `MemoryContext`: LLM 上下文

#### embedding.py (25 行)
- `EmbeddingService`: Embedding 服务接口
- 支持单条/批量 embedding

#### es_schema.py (90 行)
- `INDEX_SETTINGS`: ES 索引配置
- `INDEX_ALIAS`: 索引别名
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

#### worker.py (170 行)
- `IndexingWorker`: 任务处理器
- Pull 消费模式
- 批量 embedding
- Bulk ES 写入
- 幂等性保证

### 3. Facade 层

#### memory_service.py (100 行)
- `NPCMemoryService`: Facade 类
- 组合各模块功能
- 保持向后兼容
- 缓存集成

#### es_client.py (70 行)
- `create_es_client()`: 创建 ES 客户端
- `initialize_index()`: 索引初始化
- `check_es_health()`: 健康检查

## 数据流

### 同步写入流程

```
Memory对象
    ↓
MemoryWriter.add_memory()
    ↓
生成 Embedding
    ↓
ES.index()
    ↓
返回 memory_id
```

### 异步写入流程

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

### 检索流程

```
查询请求
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
返回 Memory 列表
```

## 配置管理

所有配置通过环境变量：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ES_URL` | http://localhost:9200 | ES 连接地址 |
| `INDEX_ASYNC_ENABLED` | false | 异步索引开关 |
| `PUBSUB_PROJECT_ID` | - | GCP 项目 ID |
| `PUBSUB_TOPIC` | index-tasks | Pub/Sub Topic |
| `PUBSUB_SUBSCRIPTION` | index-tasks-sub | Pub/Sub 订阅 |

## 依赖关系

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

## 使用场景

### 场景1: 开发调试（同步模式）

```python
from src.es_client import create_es_client
from src.memory import EmbeddingService
from src.memory_service import NPCMemoryService

es = create_es_client()
embedder = EmbeddingService()
service = NPCMemoryService(es, embedder)

# 直接写入，即刻可查
service.add_memory(memory)
results = service.search_memories(...)
```

### 场景2: 生产环境（异步模式）

```python
from src.indexing import PubSubPublisher

publisher = PubSubPublisher()
service = NPCMemoryService(es, embedder, pubsub_publisher=publisher)

# 设置环境变量
os.environ["INDEX_ASYNC_ENABLED"] = "true"

# 发布到队列，异步处理
service.add_memory(memory)
```

### 场景3: Worker 部署

```bash
# Terminal 1: 启动 Worker
python examples/run_worker.py

# Terminal 2: 发布任务
python examples/publish_task.py
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

### 3. 为什么选择 Pull 模式？
- 简单可靠，Worker 控制消费速率
- 便于本地开发调试
- 后续可扩展 Push 模式

### 4. 如何保证幂等性？
- 使用 `task_id` 作为 ES `_id`
- 重复消息覆盖，不产生重复记录
- 消息重试安全

## 性能考虑

### 批量处理
- Worker 批量 pull (max_messages=10)
- 批量 embedding (减少模型调用)
- Bulk ES 写入 (batch_size=50)

### 查询优化
- Routing by npc_id (单分片查询)
- 只返回必要字段
- 向量索引 HNSW

### 扩展性
- Worker 可多实例部署
- 无状态设计
- 水平扩展

## 测试建议

### 单元测试
```python
# test_memory_models.py
# test_memory_search.py
# test_memory_write.py
# test_indexing_tasks.py
```

### 集成测试
```python
# test_sync_flow.py
# test_async_flow.py
# test_worker.py
```

### E2E 测试
```bash
# 启动 ES、Worker
# 发布任务
# 验证索引
# 执行检索
```

## 监控指标

建议监控：
- Pub/Sub 未 ack 消息数
- Worker 处理速率
- ES 索引延迟
- Embedding 调用次数
- 错误率

## 后续优化

1. **真实 Embedding**: 集成 BGE 模型
2. **缓存优化**: Redis 缓存热数据
3. **监控集成**: Prometheus + Grafana
4. **Push 模式**: HTTP 端点接收推送
5. **Cloud Run**: 容器化部署
6. **死信队列**: 处理永久失败消息

## 总结

本项目通过模块化设计，实现了：
- ✅ 职责清晰的代码组织
- ✅ 灵活的同步/异步模式
- ✅ 可横向扩展的架构
- ✅ 完整的文档和示例
- ✅ 简洁优雅的实现

符合最小化改动、不过度设计、保持简洁的原则。
