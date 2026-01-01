"""
Memory search functionality: BM25 + Vector + RRF fusion
"""

from typing import List, Optional
from datetime import datetime
import math
import hashlib

from .models import Memory, MemoryType


class MemorySearcher:
    """Handles hybrid search with BM25, Vector and RRF fusion"""

    def __init__(self, es_client, embedding_service, index_alias: str = "npc_memories"):
        self.es = es_client
        self.embedder = embedding_service
        self.index_alias = index_alias

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

        if memory_types:
            filters.append({
                "terms": {"memory_type": [t.value for t in memory_types]}
            })

        if time_range_days:
            filters.append({
                "range": {
                    "timestamp": {
                        "gte": f"now-{time_range_days}d"
                    }
                }
            })

        # Execute both searches in parallel
        bm25_results = self._bm25_search(query, filters, npc_id, top_k * 2)
        vector_results = self._vector_search(query, filters, npc_id, top_k * 2)

        # RRF fusion
        fused_results = self._rrf_fusion(bm25_results, vector_results, top_k)

        # Apply memory decay
        memories = self._apply_memory_decay(fused_results)

        return memories

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
                       "importance", "timestamp", "emotion_tags"]
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
                       "importance", "timestamp", "emotion_tags"]
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
        top_k: int,
        k: int = 60
    ) -> List[dict]:
        """
        Reciprocal Rank Fusion
        RRF_score = sum(1 / (k + rank_i))
        """
        # Build rank dictionaries
        bm25_ranks = {r["id"]: i + 1 for i, r in enumerate(bm25_results)}
        vector_ranks = {r["id"]: i + 1 for i, r in enumerate(vector_results)}

        # Merge all document IDs
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())

        # Calculate RRF scores
        rrf_scores = []
        for doc_id in all_ids:
            score = 0
            if doc_id in bm25_ranks:
                score += 1.0 / (k + bm25_ranks[doc_id])
            if doc_id in vector_ranks:
                score += 1.0 / (k + vector_ranks[doc_id])

            # Get original document
            doc = next(
                (r["doc"] for r in bm25_results + vector_results if r["id"] == doc_id),
                None
            )
            if doc:
                rrf_scores.append({"id": doc_id, "rrf_score": score, "doc": doc})

        # Sort by RRF score
        rrf_scores.sort(key=lambda x: x["rrf_score"], reverse=True)

        return rrf_scores[:top_k]

    def _apply_memory_decay(self, results: List[dict]) -> List[Memory]:
        """
        Apply memory decay: older memories have lower importance
        Decay formula: decayed_importance = importance * exp(-lambda * days)
        """
        decay_lambda = 0.01
        now = datetime.now()

        memories = []
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
            memories.append(memory)

        # Re-sort by decayed importance
        memories.sort(key=lambda m: m.importance, reverse=True)
        return memories

    @staticmethod
    def cache_key(player_id: str, npc_id: str, query: str) -> str:
        """Generate cache key for search results"""
        key = f"{player_id}:{npc_id}:{query}"
        return hashlib.md5(key.encode()).hexdigest()
