from typing import List

from infra.embeddings import embed


def embed_qwen_v4(text: str, dim: int = 1024, retry: int = 2, backoff: float = 0.8) -> List[float]:
    """
    Deprecated wrapper kept for compatibility. Delegates to infra.embeddings.embed.
    """
    return embed(text)
