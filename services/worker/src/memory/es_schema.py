"""
Elasticsearch index schema and settings
"""

import os
from datetime import datetime


# Index alias for memories
INDEX_ALIAS = "npc_memories"

# Vector dimension (from env, must match embedding model output)
# Vector dimension (from env, must match embedding model output)
INDEX_VECTOR_DIMS = int(os.getenv("INDEX_VECTOR_DIMS", "4096"))


def get_index_settings(vector_dims: int = None) -> dict:
    """
    Get index settings with configurable vector dimension.
    Args:
        vector_dims: Override vector dimension (default: INDEX_VECTOR_DIMS)
    """
    dims = vector_dims or INDEX_VECTOR_DIMS
    settings = _BASE_INDEX_SETTINGS.copy()
    settings["mappings"] = _get_mappings(dims)
    return settings


# ES index settings (without mappings)
_BASE_INDEX_SETTINGS = {
    "settings": {
        "number_of_shards": 30,
        "number_of_replicas": 1,
        "index.routing.allocation.require.data": "hot",

        # Write optimization
        "refresh_interval": "5s",
        "translog.durability": "async",
        "translog.sync_interval": "5s",

        # Analyzer configuration
        "analysis": {
            "analyzer": {
                "memory_analyzer": {
                    "type": "custom",
                    "tokenizer": "ik_max_word",
                    "filter": ["lowercase", "memory_synonym"]
                }
            },
            "filter": {
                "memory_synonym": {
                    "type": "synonym",
                    "synonyms": [
                        "送礼,赠送,给予",
                        "帮助,协助,支援",
                        "感谢,谢谢,多谢"
                    ]
                }
            }
        }
    }
}


def _get_mappings(dims: int) -> dict:
    """Generate mappings with specified vector dimension"""
    return {
        "properties": {
            "player_id": {"type": "keyword"},
            "npc_id": {"type": "keyword"},
            "memory_type": {"type": "keyword"},

            "content": {
                "type": "text",
                "analyzer": "memory_analyzer",
                "search_analyzer": "ik_smart"
            },

            # Vector field - critical configuration
            "content_vector": {
                "type": "dense_vector",
                "dims": dims,
                "index": True,
                "similarity": "cosine",
                "index_options": {
                    "type": "hnsw",
                    "m": 16,
                    "ef_construction": 100
                }
            },

            "emotion_tags": {"type": "keyword"},
            "importance": {"type": "float"},
            "timestamp": {"type": "date"},

            "game_context": {
                "type": "object",
                "properties": {
                    "location": {"type": "keyword"},
                    "quest_id": {"type": "keyword"},
                    "scene": {"type": "keyword"}
                }
            }
        }
    }


# Backward compatibility: static settings with default dims
INDEX_SETTINGS = get_index_settings()


def create_index_if_not_exists(es_client, index_name: str = None):
    """Create index with proper settings if not exists"""
    index_name = index_name or INDEX_ALIAS

    if not es_client.indices.exists(index=index_name):
        es_client.indices.create(index=index_name, body=INDEX_SETTINGS)
        return True
    return False
