"""
Example: Rollover index with new vector dimension

Usage:
    # Rollover with current dimension setting
    python examples/rollover_index.py

    # Rollover with custom dimension (e.g., for Qwen3-Embedding-8B which outputs 4096)
    INDEX_VECTOR_DIMS=4096 python examples/rollover_index.py

Environment variables:
    - ES_URL: Elasticsearch URL (default: http://localhost:9200)
    - ES_API_KEY: Elastic Cloud API Key (optional, for cloud auth)
    - INDEX_VECTOR_DIMS: New vector dimension (default: 1024)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.es_client import create_es_client, create_index_with_rollover
from src.memory import INDEX_VECTOR_DIMS


def main():
    """Rollover index with new settings"""
    print("=== Index Rollover ===")
    print(f"Vector dimension: {INDEX_VECTOR_DIMS}")

    # Connect to ES
    print("\nConnecting to Elasticsearch...")
    es = create_es_client()
    print(f"Connected to cluster: {es.info()['cluster_name']}")

    # Confirm before proceeding
    print("\nThis will create a new index and switch the alias.")
    print("Old index will remain (can be deleted manually after data migration).")
    confirm = input("Continue? [y/N]: ").strip().lower()

    if confirm != 'y':
        print("Aborted.")
        return

    # Perform rollover
    print("\nPerforming rollover...")
    new_index = create_index_with_rollover(es, vector_dims=INDEX_VECTOR_DIMS)

    print(f"\nRollover complete!")
    print(f"New index: {new_index}")
    print("\nNote: Old index data is not migrated automatically.")
    print("For data migration, you can use ES reindex API or re-embed all documents.")


if __name__ == "__main__":
    main()
