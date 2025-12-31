"""
Elasticsearch index schema and settings
"""


# Index alias for memories
INDEX_ALIAS = "npc_memories"


# ES index settings and mappings
INDEX_SETTINGS = {
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
    },

    "mappings": {
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
                "dims": 1024,
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
}


def create_index_if_not_exists(es_client, index_name: str = None):
    """Create index with proper settings if not exists"""
    index_name = index_name or INDEX_ALIAS

    if not es_client.indices.exists(index=index_name):
        es_client.indices.create(index=index_name, body=INDEX_SETTINGS)
        return True
    return False
