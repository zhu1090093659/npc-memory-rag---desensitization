"""
Memory search functionality: BM25 + Vector + RRF fusion
"""

import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import math
import hashlib

from .models import Memory, MemoryType
from src import get_env, get_env_int

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


# Thread pool size for parallel BM25 + Vector search
SEARCH_THREAD_POOL_SIZE = get_env_int("SEARCH_THREAD_POOL_SIZE")

_RERANK_TRUE_VALUES = ("1", "true", "yes", "y", "on")
_RERANK_FALSE_VALUES = ("0", "false", "no", "n", "off")


def _get_env_bool_optional(name: str, default: bool) -> bool:
    """Parse optional bool env var; return default if missing/invalid."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    v = str(raw).strip().lower()
    if v in _RERANK_TRUE_VALUES:
        return True
    if v in _RERANK_FALSE_VALUES:
        return False
    return default


def _get_env_int_optional(name: str, default: int) -> int:
    """Parse optional int env var; return default if missing/invalid."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _safe_one_line(text: str) -> str:
    """Normalize text into a safe single-line string for prompts."""
    if text is None:
        return ""
    return str(text).replace("\r", " ").replace("\n", " ").strip()


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars (characters), keeping it single-line."""
    t = _safe_one_line(text)
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[:max_chars] + "..."


def _extract_json_block(text: str) -> str:
    """
    Extract the first JSON object or array from a model response.
    Fail open by returning empty string when not found.
    """
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
        return t
    obj_start = t.find("{")
    obj_end = t.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        return t[obj_start:obj_end + 1]
    arr_start = t.find("[")
    arr_end = t.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        return t[arr_start:arr_end + 1]
    return ""


def _parse_ranked_ids(raw_text: str, candidate_ids: List[str]) -> Optional[List[str]]:
    """
    Parse ranked ids from LLM response.
    Accepted formats:
    - {"ranked_ids": ["id1", "id2", ...]}
    - ["id1", "id2", ...]
    """
    json_text = _extract_json_block(raw_text)
    if not json_text:
        return None

    try:
        obj = json.loads(json_text)
    except Exception:
        return None

    ranked: List[str] = []
    if isinstance(obj, dict):
        v = obj.get("ranked_ids")
        if isinstance(v, list):
            ranked = [str(x) for x in v if str(x).strip()]
    elif isinstance(obj, list):
        ranked = [str(x) for x in obj if str(x).strip()]

    if not ranked:
        return None

    allowed = set(candidate_ids)
    seen = set()
    out: List[str] = []
    for rid in ranked:
        if rid in allowed and rid not in seen:
            out.append(rid)
            seen.add(rid)
    if not out:
        return None
    return out


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

        # Apply memory decay then rerank with multi-level soft penalties.
        # Keep a small pool for optional LLM reranking (fail-open, disabled by default).
        pool_k = self._soft_rerank_pool_size(top_k, candidate_k)
        soft_ranked = self._rerank_with_soft_penalty(
            fused_results=fused_results,
            top_k=pool_k,
            preferred_types=memory_types,
        )
        return self._maybe_llm_rerank(query=query, soft_ranked=soft_ranked, top_k=top_k)

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
    def _soft_rerank_pool_size(top_k: int, candidate_k: int) -> int:
        """
        Determine how many items to keep after soft rerank.
        Keep enough headroom for optional LLM rerank, but cap by candidate_k.
        """
        if top_k <= 0:
            return 0
        enabled = _get_env_bool_optional("RERANK_ENABLED", False)
        model = (os.getenv("RERANK_MODEL") or "").strip()
        if not enabled or not model:
            return top_k
        candidate_limit = _get_env_int_optional("RERANK_CANDIDATE_LIMIT", 20)
        keep = max(top_k, max(1, candidate_limit))
        return min(max(top_k, keep), max(top_k, candidate_k))

    def _maybe_llm_rerank(self, query: str, soft_ranked: List[Memory], top_k: int) -> List[Memory]:
        """
        Optional LLM rerank step (single call).
        Fail open: returns soft_ranked[:top_k] on any error.
        """
        if top_k <= 0:
            return []
        if not soft_ranked:
            return []

        enabled = _get_env_bool_optional("RERANK_ENABLED", False)
        model = (os.getenv("RERANK_MODEL") or "").strip()
        if not enabled or not model:
            return soft_ranked[:top_k]
        if OpenAI is None:
            return soft_ranked[:top_k]

        api_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("MODELSCOPE_API_KEY") or "").strip()
        base_url = (os.getenv("EMBEDDING_BASE_URL") or os.getenv("MODELSCOPE_BASE_URL") or "").strip()
        if not api_key or not base_url:
            return soft_ranked[:top_k]

        timeout_seconds = _get_env_int_optional("RERANK_TIMEOUT_SECONDS", 10)
        content_max_chars = _get_env_int_optional("RERANK_CONTENT_MAX_CHARS", 240)
        candidate_limit = _get_env_int_optional("RERANK_CANDIDATE_LIMIT", 20)
        n = min(len(soft_ranked), max(top_k, max(1, candidate_limit)))
        candidates = soft_ranked[:n]

        items: List[Dict[str, Any]] = []
        candidate_ids: List[str] = []
        for m in candidates:
            candidate_ids.append(m.id)
            items.append(
                {
                    "id": m.id,
                    "content": _truncate(m.content, content_max_chars),
                    "memory_type": getattr(m.memory_type, "value", str(m.memory_type)),
                    "importance": float(getattr(m, "importance", 0.0) or 0.0),
                }
            )

        prompt = (
            "你是一个检索精排器。给定用户查询 query 和候选记忆列表 items，"
            "请按与 query 的相关性从高到低对 items 排序。\n\n"
            "约束：\n"
            "- 只能使用给定 items 的信息，不要臆造。\n"
            "- 必须输出严格 JSON，不要输出 markdown。\n"
            "- 输出格式必须是：{\"ranked_ids\": [\"id1\", \"id2\", ...]}，包含所有候选 id，且不重复。\n\n"
            f"query: {query}\n"
            f"items: {json.dumps(items, ensure_ascii=False)}\n"
        )

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful ranking assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                timeout=timeout_seconds,
            )
            text = (resp.choices[0].message.content or "").strip()
            ranked_ids = _parse_ranked_ids(text, candidate_ids=candidate_ids)
            if not ranked_ids:
                return soft_ranked[:top_k]

            id_to_mem = {m.id: m for m in candidates}
            ordered: List[Memory] = []
            for rid in ranked_ids:
                mm = id_to_mem.get(rid)
                if mm is not None:
                    ordered.append(mm)
            # Append any missing candidates in original order (fail open)
            seen = set(ranked_ids)
            for m in candidates:
                if m.id not in seen:
                    ordered.append(m)

            tail = soft_ranked[n:]
            return (ordered + tail)[:top_k]
        except Exception:
            return soft_ranked[:top_k]

    @staticmethod
    def cache_key(player_id: str, npc_id: str, query: str) -> str:
        """Generate cache key for search results"""
        key = f"{player_id}:{npc_id}:{query}"
        return hashlib.md5(key.encode()).hexdigest()
