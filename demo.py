#!/usr/bin/env python3
"""
NPC Memory RAG Demo - 本地可运行演示
无需安装ES，使用内存模拟，展示核心逻辑

运行方式：python demo.py
"""

import math
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum
import json


# ============================================================
# 模型定义
# ============================================================

class MemoryType(Enum):
    DIALOGUE = "dialogue"
    QUEST = "quest"
    TRADE = "trade"
    GIFT = "gift"
    COMBAT = "combat"


@dataclass
class Memory:
    id: str
    player_id: str
    npc_id: str
    memory_type: MemoryType
    content: str
    content_vector: List[float] = field(default_factory=list)
    emotion_tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================
# 简化的Embedding服务（模拟）
# ============================================================

class SimpleEmbedding:
    """
    简化的embedding实现
    实际项目中使用 sentence-transformers 或 API
    这里用关键词匹配模拟语义相似度
    """
    
    # 语义相关词组
    SEMANTIC_GROUPS = [
        {"礼物", "送", "赠送", "给", "收到", "感谢"},
        {"任务", "帮助", "完成", "协助", "找到", "找回"},
        {"交易", "买", "卖", "价格", "金币", "购买"},
        {"战斗", "打", "攻击", "保护", "敌人", "怪物"},
        {"记得", "记忆", "之前", "上次", "以前", "还记得"},
    ]
    
    def embed(self, text: str) -> List[float]:
        """生成伪向量（基于关键词）"""
        vector = [0.0] * 64  # 64维简化向量
        
        for i, group in enumerate(self.SEMANTIC_GROUPS):
            for word in group:
                if word in text:
                    # 在对应维度上设置值
                    vector[i * 10: i * 10 + 10] = [1.0] * 10
                    break
        
        # 添加随机噪声使向量更真实
        for j in range(len(vector)):
            vector[j] += random.uniform(-0.1, 0.1)
        
        return vector
    
    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)


# ============================================================
# 内存模拟ES存储
# ============================================================

class InMemoryStore:
    """内存存储，模拟ES行为"""
    
    def __init__(self):
        self.documents: Dict[str, Memory] = {}
        self.embedder = SimpleEmbedding()
    
    def index(self, memory: Memory):
        """索引文档"""
        if not memory.content_vector:
            memory.content_vector = self.embedder.embed(memory.content)
        self.documents[memory.id] = memory
    
    def bm25_search(
        self, 
        query: str, 
        player_id: str, 
        npc_id: str, 
        top_k: int = 10
    ) -> List[tuple]:
        """BM25关键词搜索（简化实现）"""
        query_terms = set(query)
        results = []
        
        for doc_id, memory in self.documents.items():
            # 过滤条件
            if memory.player_id != player_id or memory.npc_id != npc_id:
                continue
            
            # 简单的词匹配打分
            content_terms = set(memory.content)
            overlap = len(query_terms & content_terms)
            score = overlap / (len(query_terms) + 1)
            
            if score > 0:
                results.append((doc_id, score, memory))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    def vector_search(
        self,
        query: str,
        player_id: str,
        npc_id: str,
        top_k: int = 10
    ) -> List[tuple]:
        """向量语义搜索"""
        query_vector = self.embedder.embed(query)
        results = []
        
        for doc_id, memory in self.documents.items():
            # 过滤条件
            if memory.player_id != player_id or memory.npc_id != npc_id:
                continue
            
            # 余弦相似度
            score = SimpleEmbedding.cosine_similarity(query_vector, memory.content_vector)
            results.append((doc_id, score, memory))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


# ============================================================
# NPC记忆服务
# ============================================================

class NPCMemoryServiceDemo:
    """演示用的记忆服务"""
    
    def __init__(self):
        self.store = InMemoryStore()
    
    def add_memory(self, memory: Memory):
        """添加记忆"""
        self.store.index(memory)
        print(f"  ✓ 存储记忆: [{memory.memory_type.value}] {memory.content[:30]}...")
    
    def hybrid_search(
        self,
        player_id: str,
        npc_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Memory]:
        """
        混合检索 = BM25 + Vector + RRF融合
        这是招聘要求第4点的核心能力展示
        """
        print(f"\n🔍 执行混合检索...")
        print(f"   查询: \"{query}\"")
        
        # 1. BM25搜索
        bm25_results = self.store.bm25_search(query, player_id, npc_id, top_k * 2)
        print(f"   BM25召回: {len(bm25_results)} 条")
        
        # 2. 向量搜索
        vector_results = self.store.vector_search(query, player_id, npc_id, top_k * 2)
        print(f"   Vector召回: {len(vector_results)} 条")
        
        # 3. RRF融合
        fused = self._rrf_fusion(bm25_results, vector_results, top_k)
        print(f"   RRF融合后: {len(fused)} 条")
        
        # 4. 应用记忆衰减
        final_results = self._apply_decay(fused)
        
        return final_results
    
    def _rrf_fusion(
        self,
        bm25_results: List[tuple],
        vector_results: List[tuple],
        top_k: int,
        k: int = 60
    ) -> List[Memory]:
        """
        Reciprocal Rank Fusion
        公式: RRF(d) = Σ 1/(k + rank_i(d))
        
        这是招聘要求中"混合检索"的关键技术
        """
        # 构建排名
        bm25_ranks = {r[0]: i + 1 for i, r in enumerate(bm25_results)}
        vector_ranks = {r[0]: i + 1 for i, r in enumerate(vector_results)}
        
        # 合并文档
        all_docs = {}
        for doc_id, _, memory in bm25_results + vector_results:
            if doc_id not in all_docs:
                all_docs[doc_id] = memory
        
        # 计算RRF分数
        rrf_scores = []
        for doc_id, memory in all_docs.items():
            score = 0.0
            if doc_id in bm25_ranks:
                score += 1.0 / (k + bm25_ranks[doc_id])
            if doc_id in vector_ranks:
                score += 1.0 / (k + vector_ranks[doc_id])
            rrf_scores.append((score, memory))
        
        # 排序并返回
        rrf_scores.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in rrf_scores[:top_k]]
    
    def _apply_decay(self, memories: List[Memory]) -> List[Memory]:
        """
        记忆衰减：模拟人类记忆遗忘曲线
        decayed = importance × e^(-λ × days)
        """
        decay_lambda = 0.01
        now = datetime.now()
        
        for m in memories:
            days_ago = (now - m.timestamp).days
            m.importance = m.importance * math.exp(-decay_lambda * days_ago)
        
        # 按衰减后的重要性排序
        memories.sort(key=lambda m: m.importance, reverse=True)
        return memories
    
    def get_llm_context(
        self,
        player_id: str,
        npc_id: str,
        current_query: str
    ) -> str:
        """
        为LLM生成上下文
        这是招聘要求第10点：与AI团队协作
        """
        memories = self.hybrid_search(player_id, npc_id, current_query)
        
        if not memories:
            return "这是你第一次见到这个玩家。"
        
        # 构建上下文
        context_parts = ["你对这个玩家的记忆："]
        for i, m in enumerate(memories, 1):
            days_ago = (datetime.now() - m.timestamp).days
            time_desc = "今天" if days_ago == 0 else f"{days_ago}天前"
            context_parts.append(f"{i}. [{time_desc}] {m.content}")
        
        # 关系评估
        positive = sum(1 for m in memories if any(t in m.emotion_tags for t in ["感谢", "友好", "信任"]))
        negative = sum(1 for m in memories if any(t in m.emotion_tags for t in ["愤怒", "失望"]))
        
        if positive > negative:
            context_parts.append(f"\n整体关系：友好 (正面互动{positive}次)")
        elif negative > positive:
            context_parts.append(f"\n整体关系：紧张 (负面互动{negative}次)")
        else:
            context_parts.append(f"\n整体关系：中立")
        
        return "\n".join(context_parts)


# ============================================================
# 演示场景
# ============================================================

def create_sample_memories(service: NPCMemoryServiceDemo):
    """创建示例记忆数据"""
    
    print("\n📝 初始化NPC记忆数据...")
    
    memories = [
        Memory(
            id="m1",
            player_id="player_001",
            npc_id="blacksmith_01",
            memory_type=MemoryType.QUEST,
            content="玩家帮助铁匠找回了被盗的祖传锤子，铁匠非常感激",
            emotion_tags=["感谢", "信任"],
            importance=0.9,
            timestamp=datetime.now() - timedelta(days=7)
        ),
        Memory(
            id="m2",
            player_id="player_001",
            npc_id="blacksmith_01",
            memory_type=MemoryType.GIFT,
            content="玩家送给铁匠一瓶上好的麦酒作为礼物",
            emotion_tags=["感谢", "友好"],
            importance=0.7,
            timestamp=datetime.now() - timedelta(days=5)
        ),
        Memory(
            id="m3",
            player_id="player_001",
            npc_id="blacksmith_01",
            memory_type=MemoryType.TRADE,
            content="玩家购买了一把精钢长剑，支付了150金币",
            emotion_tags=["满意"],
            importance=0.5,
            timestamp=datetime.now() - timedelta(days=3)
        ),
        Memory(
            id="m4",
            player_id="player_001",
            npc_id="blacksmith_01",
            memory_type=MemoryType.DIALOGUE,
            content="玩家询问铁匠关于传说中龙火锻造技术的传闻",
            emotion_tags=["好奇"],
            importance=0.4,
            timestamp=datetime.now() - timedelta(days=1)
        ),
        Memory(
            id="m5",
            player_id="player_001",
            npc_id="blacksmith_01",
            memory_type=MemoryType.COMBAT,
            content="玩家保护铁匠铺免受强盗袭击，击退了三名歹徒",
            emotion_tags=["感谢", "尊敬", "信任"],
            importance=0.95,
            timestamp=datetime.now() - timedelta(days=2)
        ),
        
        # 另一个玩家的记忆（不应被检索到）
        Memory(
            id="m6",
            player_id="player_002",
            npc_id="blacksmith_01",
            memory_type=MemoryType.TRADE,
            content="另一个玩家买了一把匕首",
            emotion_tags=[],
            importance=0.3,
            timestamp=datetime.now()
        ),
    ]
    
    for m in memories:
        service.add_memory(m)


def demo_search_scenarios(service: NPCMemoryServiceDemo):
    """演示不同的检索场景"""
    
    player_id = "player_001"
    npc_id = "blacksmith_01"
    
    print("\n" + "="*60)
    print("🎮 场景1：玩家再次拜访铁匠")
    print("="*60)
    
    query1 = "你还记得我吗？"
    context1 = service.get_llm_context(player_id, npc_id, query1)
    
    print(f"\n📜 生成的LLM上下文：")
    print("-"*40)
    print(context1)
    
    print("\n💬 模拟NPC回复：")
    print("-"*40)
    print("""
铁匠抬起头，眼中闪过认出的光芒：

"哦！是你啊，老朋友！我怎么会忘记你呢？你不仅帮我找回了
祖传的锤子，前两天还保护我的铺子免遭强盗洗劫。说起来，
那瓶麦酒味道真不错，我还留着舍不得喝完呢。

对了，上次你买的那把精钢长剑用着还顺手吗？你之前问的龙火
锻造术...我最近打听到一些消息，有兴趣听听吗？"
""")
    
    print("\n" + "="*60)
    print("🎮 场景2：玩家询问礼物相关")
    print("="*60)
    
    query2 = "你还记得我送你的礼物吗？"
    memories = service.hybrid_search(player_id, npc_id, query2)
    
    print(f"\n📋 检索到的相关记忆：")
    print("-"*40)
    for i, m in enumerate(memories, 1):
        print(f"{i}. [{m.memory_type.value}] {m.content}")
        print(f"   重要性: {m.importance:.2f}, 情感: {m.emotion_tags}")
    
    print("\n" + "="*60)
    print("🎮 场景3：玩家询问交易历史")
    print("="*60)
    
    query3 = "我之前在你这买过什么？"
    memories = service.hybrid_search(player_id, npc_id, query3)
    
    print(f"\n📋 检索到的相关记忆：")
    print("-"*40)
    for i, m in enumerate(memories, 1):
        print(f"{i}. [{m.memory_type.value}] {m.content}")


def explain_architecture():
    """解释架构设计如何匹配招聘要求"""
    
    print("\n" + "="*60)
    print("📚 架构设计与招聘要求映射")
    print("="*60)
    
    mappings = """
┌─────────────────────────────────────────────────────────────┐
│                   招聘要求 → 项目实现                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ 1. AI Search & RAG Infrastructure                          │
│    → 基于ES的记忆存储，为LLM提供RAG上下文                    │
│                                                             │
│ 2. High-availability, High-throughput                      │
│    → 按npc_id routing，跨AZ部署，连接池复用                 │
│                                                             │
│ 3. Index & Mapping Strategies                              │
│    → keyword/text/dense_vector混合schema                   │
│    → 按月滚动索引，冷热分离                                 │
│                                                             │
│ 4. Vector Retrieval Pipelines                              │
│    → BM25 + ANN + RRF混合检索 ⭐ 核心亮点                   │
│                                                             │
│ 5. Optimize Performance                                    │
│    → Routing优化，结果缓存，批量embedding                   │
│                                                             │
│ 6. Data Ingestion Pipelines                                │
│    → Kafka解耦，批量写入，异步embedding                     │
│                                                             │
│ 7. Troubleshoot Production Issues                          │
│    → 延迟监控，GC监控，慢查询日志                           │
│                                                             │
│ 8-9. Operational Excellence                                │
│    → ILM策略，SLA定义，容量规划                             │
│                                                             │
│ 10. Collaborate with AI/ML Teams                           │
│    → get_llm_context() 标准化接口 ⭐ 你的差异化优势         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
"""
    print(mappings)


# ============================================================
# 主程序
# ============================================================

def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        🎮 NPC Memory RAG System - 演示Demo                    ║
║                                                               ║
║    展示：混合检索 / RRF融合 / 记忆衰减 / LLM上下文生成        ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    # 初始化服务
    service = NPCMemoryServiceDemo()
    
    # 创建示例数据
    create_sample_memories(service)
    
    # 演示检索场景
    demo_search_scenarios(service)
    
    # 解释架构
    explain_architecture()
    
    print("\n" + "="*60)
    print("✅ 演示完成！")
    print("="*60)
    print("""
📁 项目文件说明：
├── docs/ARCHITECTURE.md      - 详细架构设计文档
├── docs/api/API_REFERENCE.md - API 接口文档
├── docs/api/openapi.yaml     - OpenAPI 规范
├── src/memory_service.py     - 完整实现代码（Facade层）
├── src/indexing/push_app.py  - Cloud Run Push Worker
├── demo.py                   - 本演示脚本（无依赖）
└── docker-compose.yml        - 本地 ES 集群配置

☁️  云端部署（已上线）：
├── Cloud Run (asia-southeast1)    - Push Worker 服务
├── Pub/Sub                   - 消息队列 + DLQ
├── Elastic Cloud             - 向量数据库
└── Secret Manager            - 密钥管理

🔗 API 端点：
├── POST /pubsub/push   - Pub/Sub 消息接收
├── GET  /health        - 健康检查
├── GET  /ready         - 就绪检查（验证ES连接）
├── GET  /docs          - Swagger UI
└── GET  /metrics       - Prometheus 指标

💡 面试时讲解顺序：
1. 用业务场景开场（NPC个性化记忆）
2. 画架构图，讲数据流（Game → Pub/Sub → Worker → ES）
3. 重点讲RRF混合检索（代码级细节）
4. 讲routing优化、ILM策略
5. 展示云端部署成果（Cloud Run + Pub/Sub Push）
6. 强调你的优势：懂AI应用层需求 + 云原生实践
""")


if __name__ == "__main__":
    main()
