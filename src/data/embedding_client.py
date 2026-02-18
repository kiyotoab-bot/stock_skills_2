"""TEI (Text Embeddings Inference) REST API client (KIK-420).

Provides embedding generation via Hugging Face TEI Docker service.
Graceful degradation: returns None when TEI is unavailable.
"""

import os
import time

import requests

TEI_URL = os.environ.get("TEI_URL", "http://localhost:8081")

_available: bool | None = None
_available_checked_at: float = 0.0
_AVAILABILITY_TTL = 30.0  # re-check every 30s


def is_available() -> bool:
    """Check if TEI service is reachable (result cached for 30s)."""
    global _available, _available_checked_at
    now = time.time()
    if _available is not None and (now - _available_checked_at) < _AVAILABILITY_TTL:
        return _available
    try:
        resp = requests.get(f"{TEI_URL}/health", timeout=3)
        _available = resp.status_code == 200
    except Exception:
        _available = False
    _available_checked_at = now
    return _available


def get_embedding(text: str) -> list[float] | None:
    """Get embedding vector from TEI. Returns None on failure."""
    if not text:
        return None
    try:
        resp = requests.post(
            f"{TEI_URL}/embed",
            json={"inputs": text},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
    except Exception:
        pass
    return None


def reset_cache():
    """Reset availability cache (for testing)."""
    global _available, _available_checked_at
    _available = None
    _available_checked_at = 0.0
