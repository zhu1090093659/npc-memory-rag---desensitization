"""
NPC Memory RAG System
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv():
    """Load .env from nearest parents (preferred) with safe fallback."""
    here = Path(__file__).resolve()

    # Search upward for repo-root .env (works for local dev and containers)
    # Note: override=False to keep real env (Cloud Run, CI) as source of truth.
    for p in here.parents:
        env_path = p / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            return

    # Fallback: service-level .env next to src/ (local dev convenience)
    service_env = here.parent.parent / ".env"
    if service_env.exists():
        load_dotenv(service_env, override=False)


def get_env(name: str) -> str:
    """Get required env var, raise if missing/empty."""
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_env_int(name: str) -> int:
    """Get required int env var, raise if missing/invalid."""
    raw = get_env(name)
    try:
        return int(raw)
    except Exception as e:
        raise RuntimeError(f"Invalid int env var {name}={raw!r}") from e


def get_env_bool(name: str) -> bool:
    """Get required bool env var, raise if missing/invalid."""
    raw = get_env(name).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    raise RuntimeError(f"Invalid bool env var {name}={raw!r}")


_load_dotenv()

__version__ = "1.0.0"
