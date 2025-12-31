"""
Example: Initialize Elasticsearch index

Usage:
    python examples/init_es.py

Environment variables:
    - ES_URL: Elasticsearch URL (default: http://localhost:9200)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.es_client import create_es_client, initialize_index, get_es_info, check_es_health


def main():
    """Initialize ES index"""
    print("=== Elasticsearch Initialization ===")

    # Connect to ES
    print("\nConnecting to Elasticsearch...")
    es = create_es_client()

    # Get cluster info
    info = get_es_info(es)
    print(f"\nCluster Info:")
    print(f"  Name: {info['cluster_name']}")
    print(f"  Version: {info['version']['number']}")

    # Check health
    health = check_es_health(es)
    print(f"\nCluster Health:")
    print(f"  Status: {health['status']}")
    print(f"  Nodes: {health['number_of_nodes']}")
    print(f"  Shards: {health['active_shards']}")

    # Initialize index
    print("\nInitializing index...")
    created = initialize_index(es)

    if created:
        print("✓ Index created successfully")
    else:
        print("✓ Index already exists")

    print("\nDone!")


if __name__ == "__main__":
    main()
