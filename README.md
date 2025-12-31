# NPC Memory RAG 系统

基于 Elasticsearch 和 RAG 的 NPC 记忆系统，支持同步/异步索引构建。

## 项目结构

```
npc-memory-rag/
├── src/
│   ├── memory/              # 核心记忆模块
│   │   ├── models.py        # 数据模型
│   │   ├── embedding.py     # Embedding 服务
│   │   ├── es_schema.py     # ES 索引配置
│   │   ├── search.py        # 混合检索
│   │   └── write.py         # 写入操作
│   ├── indexing/            # 异步索引模块
│   │   ├── tasks.py         # 索引任务定义
│   │   ├── pubsub_client.py # Pub/Sub 封装
│   │   └── worker.py        # Worker 处理器
│   ├── memory_service.py    # Facade 兼容层
│   └── es_client.py         # ES 客户端工具
├── examples/                # 示例脚本
│   ├── init_es.py          # 初始化 ES 索引
│   ├── publish_task.py     # 发布任务示例
│   └── run_worker.py       # 运行 Worker
├── demo.py                  # 算法演示
├── docker-compose.yml       # ES 集群配置
└── ASYNC_INDEXING.md       # 异步索引指南
```

## 核心特性

### 1. 模块化设计

- **src/memory**: 核心记忆功能模块
  - 数据模型、ES schema、检索、写入各自独立
  - 便于单元测试和复用

- **src/indexing**: 异步索引构建模块
  - 任务定义与序列化
  - Pub/Sub 客户端封装
  - Worker 消费处理

- **src/memory_service.py**: Facade 层
  - 保持向后兼容
  - 组合各模块功能
  - 统一对外接口

### 2. 混合检索（BM25 + Vector + RRF）

- BM25 关键词搜索
- 向量语义搜索
- RRF 融合排序
- 记忆衰减机制

### 3. 异步索引构建

支持两种模式：

**同步模式（默认）**
- 直接写入 Elasticsearch
- 适合开发调试

**异步模式（可选）**
- 发布任务到 Pub/Sub
- Worker 批量消费处理
- 支持横向扩展

详见 [ASYNC_INDEXING.md](ASYNC_INDEXING.md)

### 4. ES 优化设计

- 30 分片支持高并发
- 按 NPC routing 优化查询
- 向量索引 HNSW 配置
- 冷热数据分离

## 快速开始

### 1. 启动 Elasticsearch

```bash
docker-compose up -d
```

### 2. 初始化索引

```bash
pip install elasticsearch google-cloud-pubsub

python examples/init_es.py
```

### 3. 同步模式使用

```python
from src.es_client import create_es_client
from src.memory import EmbeddingService, Memory, MemoryType
from src.memory_service import NPCMemoryService

# 初始化
es = create_es_client()
embedder = EmbeddingService()
service = NPCMemoryService(es, embedder)

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

### 4. 异步模式使用

详见 [ASYNC_INDEXING.md](ASYNC_INDEXING.md)

## 环境变量

```bash
# Elasticsearch
ES_URL=http://localhost:9200

# 异步索引（可选）
INDEX_ASYNC_ENABLED=false
PUBSUB_PROJECT_ID=your-project-id
PUBSUB_TOPIC=index-tasks
PUBSUB_SUBSCRIPTION=index-tasks-sub
```

## 技术栈

- **Elasticsearch 8.11**: 混合检索、向量索引
- **Google Cloud Pub/Sub**: 任务队列
- **Python 3.8+**: 核心实现
- **Docker Compose**: 本地开发环境

## 设计原则

1. **最小化改动**: 保持现有 API 兼容，facade 模式封装
2. **不过度设计**: 先实现 pull worker，留扩展点
3. **代码简洁**: 职责清晰，模块独立，易于维护
4. **渐进增强**: 每个里程碑可独立运行和回滚

## 文档

- [架构设计](docs/ARCHITECTURE.md)
- [异步索引指南](ASYNC_INDEXING.md)
- [性能测试](docs/PERFORMANCE.md)

## 开发计划

- [x] 模块拆分（memory/indexing）
- [x] Pub/Sub 任务发布
- [x] Worker pull 消费
- [x] 本地 ES 支持
- [ ] Push 模式支持
- [ ] Cloud Run 部署
- [ ] 监控集成

## License

MIT
