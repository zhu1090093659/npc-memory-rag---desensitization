"""
Elasticsearch client initialization and utility functions
"""

import os
from datetime import datetime
from elasticsearch import Elasticsearch
from src.memory import INDEX_ALIAS, create_index_if_not_exists, get_index_settings


def create_es_client(
    hosts: list = None,
    es_url: str = None,
    **kwargs
) -> Elasticsearch:
    """
    Create and configure Elasticsearch client

    Args:
        hosts: List of ES host strings (e.g., ["localhost:9200"])
        es_url: Single ES URL (alternative to hosts)
        **kwargs: Additional Elasticsearch client options

    Returns:
        Configured Elasticsearch client
    """
    # Priority: explicit params > env vars > defaults
    if hosts is None and es_url is None:
        es_url = os.getenv("ES_URL", "http://localhost:9200")

    if es_url:
        hosts = [es_url]

    # Create client
    es = Elasticsearch(hosts, **kwargs)

    # Verify connection
    if not es.ping():
        raise ConnectionError(f"Cannot connect to Elasticsearch at {hosts}")

    return es


def initialize_index(es_client: Elasticsearch, index_name: str = None) -> bool:
    """
    Initialize memory index if not exists

    Args:
        es_client: Elasticsearch client
        index_name: Index name or alias (defaults to INDEX_ALIAS)

    Returns:
        True if index was created, False if already exists
    """
    index_name = index_name or INDEX_ALIAS
    created = create_index_if_not_exists(es_client, index_name)

    if created:
        print(f"Index '{index_name}' created successfully")
    else:
        print(f"Index '{index_name}' already exists")

    return created


def get_es_info(es_client: Elasticsearch) -> dict:
    """Get Elasticsearch cluster info"""
    return es_client.info()


def check_es_health(es_client: Elasticsearch) -> dict:
    """Check Elasticsearch cluster health"""
    return es_client.cluster.health()


def create_index_with_rollover(
    es_client: Elasticsearch,
    alias_name: str = None,
    vector_dims: int = None
) -> str:
    """
    Create new timestamped index and switch alias to it.
    Useful when changing vector dimensions or index settings.

    Args:
        es_client: Elasticsearch client
        alias_name: Alias to manage (defaults to INDEX_ALIAS)
        vector_dims: Vector dimension for new index

    Returns:
        New index name
    """
    alias_name = alias_name or INDEX_ALIAS
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_index_name = f"{alias_name}_{timestamp}"

    # Create new index with specified settings
    settings = get_index_settings(vector_dims)
    es_client.indices.create(index=new_index_name, body=settings)
    print(f"Created new index: {new_index_name}")

    # Get current indices for this alias
    old_indices = []
    if es_client.indices.exists_alias(name=alias_name):
        alias_info = es_client.indices.get_alias(name=alias_name)
        old_indices = list(alias_info.keys())

    # Atomic alias switch: remove from old, add to new
    actions = [{"add": {"index": new_index_name, "alias": alias_name}}]
    for old_index in old_indices:
        actions.append({"remove": {"index": old_index, "alias": alias_name}})

    es_client.indices.update_aliases(body={"actions": actions})
    print(f"Alias '{alias_name}' now points to: {new_index_name}")

    if old_indices:
        print(f"Old indices (can be deleted manually): {old_indices}")

    return new_index_name
