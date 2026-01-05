"""
Memory search functionality: BM25 + Vector + RRF fusion
"""

import os
from typing import List, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import math
import hashlib

from .models import Memory, MemoryType
from src import get_env, get_env_int


# Thread pool size for parallel BM25 + Vector search
SEARCH_THREAD_POOL_SIZE = get_env_int("SEARCH_THREAD_POOL_SIZE")


class MemorySearcher:
    """Handles hybrid search with BM25, Vector and RRF fusion"""

    # Shared thread pool for parallel search execution
    _executor = ThreadPoolExecutor(max_workers=SEARCH_THREAD_POOL_SIZE, thread_name_prefix="search_")

    def __init__(self, es_client, embedding_service, index_alias: str = None):
        self.es = es_client
        self.embedder = embedding_service
        self.index_alias = index_alias or get_env("INDEX_ALIAS")

    def search_memories(
        self,
        player_id: str,
        npc_id: str,
        query: str,
        top_k: int = 5,
        memory_types: List[MemoryType] = None,
        time_range_days: int = None
    ) -> List[Memory]:
        """Hybrid search: BM25 + Vector + RRF fusion"""
        # Build base filters
        filters = [
            {"term": {"player_id": player_id}},
            {"term": {"npc_id": npc_id}}
        ]

        if time_range_days:
            filters.append({
                "range": {
                    "timestamp": {
                        "gte": f"now-{time_range_days}d"
                    }
                }
            })

        # Expand candidate pool for post-filter reranking (soft penalties).
        # Keep a reasonable cap to avoid excessive ES payload.
        candidate_k = self._candidate_pool_size(top_k)

        # Execute both searches in parallel using ThreadPoolExecutor
        future_bm25 = self._executor.submit(
            self._bm25_search, query, filters, npc_id, candidate_k
        )
        future_vector = self._executor.submit(
            self._vector_search, query, filters, npc_id, candidate_k
        )

        # Wait for both results with timeout
        bm25_results = future_bm25.result(timeout=15)
        vector_results = future_vector.result(timeout=15)

        # RRF fusion (do NOT cut to top_k here; keep candidates for reranking)
        fused_results = self._rrf_fusion(bm25_results, vector_results, candidate_k)

        # Apply memory decay then rerank with multi-level soft penalties
        return self._rerank_with_soft_penalty(
            fused_results=fused_results,
            top_k=top_k,
            preferred_types=memory_types,
        )

    def _bm25_search(
        self,
        query: str,
        filters: List[dict],
        npc_id: str,
        size: int
    ) -> List[dict]:
        """BM25 keyword search"""
        # Note: ik_smart analyzer removed for Elastic Cloud Serverless compatibility
        # Use default analyzer which works for both Chinese and English
        body = {
            "size": size,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "content": query
                            }
                        }
                    ],
                    "filter": filters
                }
            },
            "_source": ["player_id", "npc_id", "content", "memory_type",
                       "importance", "timestamp", "emotion_tags", "game_context"]
        }

        # Execute search (routing disabled for Elastic Cloud Serverless compatibility)
        response = self.es.search(
            index=self.index_alias,
            body=body,
            request_timeout=10
        )

        return [
            {"id": hit["_id"], "score": hit["_score"], "doc": hit["_source"]}
            for hit in response["hits"]["hits"]
        ]

    def _vector_search(
        self,
        query: str,
        filters: List[dict],
        npc_id: str,
        size: int
    ) -> List[dict]:
        """Vector semantic search"""
        query_vector = self.embedder.embed(query)

        body = {
            "size": size,
            "query": {
                "script_score": {
                    "query": {
                        "bool": {"filter": filters}
                    },
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, 'content_vector') + 1.0",
                        "params": {"query_vector": query_vector}
                    }
                }
            },
            "_source": ["player_id", "npc_id", "content", "memory_type",
                       "importance", "timestamp", "emotion_tags", "game_context"]
        }

        # Execute search (routing disabled for Elastic Cloud Serverless compatibility)
        response = self.es.search(
            index=self.index_alias,
            body=body,
            request_timeout=10
        )

        return [
            {"id": hit["_id"], "score": hit["_score"], "doc": hit["_source"]}
            for hit in response["hits"]["hits"]
        ]

    def _rrf_fusion(
        self,
        bm25_results: List[dict],
        vector_results: List[dict],
        limit: int,
        k: int = 60
    ) -> List[dict]:
        """
        Reciprocal Rank Fusion
        RRF_score = sum(1 / (k + rank_i))
        """
        # Build rank dictionaries
        bm25_ranks = {r["id"]: i + 1 for i, r in enumerate(bm25_results)}
        vector_ranks = {r["id"]: i + 1 for i, r in enumerate(vector_results)}

        # Pre-build id -> doc mapping for O(1) lookup (optimized from O(n^2))
        doc_map = {r["id"]: r["doc"] for r in bm25_results}
        for r in vector_results:
            if r["id"] not in doc_map:
                doc_map[r["id"]] = r["doc"]

        # Merge all document IDs
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())

        # Calculate RRF scores with O(1) doc lookup
        rrf_scores = []
        for doc_id in all_ids:
            score = 0
            if doc_id in bm25_ranks:
                score += 1.0 / (k + bm25_ranks[doc_id])
            if doc_id in vector_ranks:
                score += 1.0 / (k + vector_ranks[doc_id])

            doc = doc_map.get(doc_id)
            if doc:
                rrf_scores.append({"id": doc_id, "rrf_score": score, "doc": doc})

        # Sort by RRF score
        rrf_scores.sort(key=lambda x: x["rrf_score"], reverse=True)

        return rrf_scores[:limit]

    @staticmethod
    def _candidate_pool_size(top_k: int) -> int:
        """
        Determine ES candidate pool size for reranking.
        """
        if top_k <= 0:
            return 0
        # 8x is usually enough headroom for reranking while staying lightweight.
        return min(max(top_k * 8, top_k), 200)

    def _apply_memory_decay(self, results: List[dict]) -> List[dict]:
        """
        Apply memory decay: older memories have lower importance
        Decay formula: decayed_importance = importance * exp(-lambda * days)
        """
        decay_lambda = 0.01
        now = datetime.now()

        items: List[dict] = []
        for r in results:
            doc = r["doc"]
            timestamp = datetime.fromisoformat(doc["timestamp"].replace("Z", "+00:00"))
            days_ago = (now - timestamp).days

            # Apply decay
            original_importance = doc.get("importance", 0.5)
            decayed_importance = original_importance * math.exp(-decay_lambda * days_ago)

            memory = Memory(
                id=r["id"],
                player_id=doc["player_id"],
                npc_id=doc["npc_id"],
                memory_type=MemoryType(doc["memory_type"]),
                content=doc["content"],
                emotion_tags=doc.get("emotion_tags", []),
                importance=decayed_importance,
                timestamp=timestamp,
                game_context=doc.get("game_context", {})
            )
            items.append(
                {
                    "memory": memory,
                    "rrf_score": float(r.get("rrf_score", 0.0)),
                }
            )

        return items

    @staticmethod
    def _importance_weight(importance: float, floor: float = 0.2) -> float:
        """
        Convert importance in [0, 1] to a multiplicative weight.
        floor keeps low-importance memories from becoming unrankable.
        """
        try:
            x = float(importance)
        except Exception:
            x = 0.0
        x = max(0.0, min(1.0, x))
        return floor + (1.0 - floor) * x

    @staticmethod
    def _type_weight(memory_type: MemoryType, preferred_types: Optional[List[MemoryType]]) -> float:
        """
        Apply soft penalty when memory type doesn't match preferred types.
        """
        if not preferred_types:
            return 1.0
        try:
            if memory_type in preferred_types:
                return 1.0
        except Exception:
            # Fail open: no penalty when type comparison fails.
            return 1.0
        return 0.35

    def _rerank_with_soft_penalty(
        self,
        fused_results: List[dict],
        top_k: int,
        preferred_types: Optional[List[MemoryType]],
    ) -> List[Memory]:
        """
        Multi-level post-filter rerank:
        - Base score: RRF score
        - Soft penalty: type mismatch
        - Soft penalty: low importance (decayed)
        """
        items = self._apply_memory_decay(fused_results)

        scored: List[dict] = []
        for it in items:
            m: Memory = it["memory"]
            base = float(it.get("rrf_score", 0.0))
            w_type = self._type_weight(m.memory_type, preferred_types)
            w_imp = self._importance_weight(m.importance)
            final_score = base * w_type * w_imp
            scored.append({"score": final_score, "memory": m})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return [x["memory"] for x in scored[:top_k]]

    @staticmethod
    def cache_key(player_id: str, npc_id: str, query: str) -> str:
        """Generate cache key for search results"""
        key = f"{player_id}:{npc_id}:{query}"
        return hashlib.md5(key.encode()).hexdigest()
