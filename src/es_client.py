"""
Elasticsearch client initialization and utility functions
"""

import os
from elasticsearch import Elasticsearch
from src.memory import INDEX_ALIAS, create_index_if_not_exists


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
