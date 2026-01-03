"""
NPC Memory RAG System
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv():
    """Load .env from repo root (preferred) or service directory (fallback)."""
    here = Path(__file__).resolve()
    repo_root_env = here.parents[3] / ".env"
    service_env = here.parents[1] / ".env"

    # Note: override=False to keep real env (Cloud Run, CI) as source of truth.
    if repo_root_env.exists():
        load_dotenv(repo_root_env, override=False)
        return
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
