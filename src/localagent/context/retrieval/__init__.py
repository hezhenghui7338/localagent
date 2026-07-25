"""Retrieval gateway for Warm/Cold memory and knowledge."""

from localagent.context.retrieval.gateway import (
    ALL_MISS,
    KNOWLEDGE_MISS,
    MEMORY_MISS,
    RetrievalGateway,
    get_retrieval_gateway,
)
from localagent.context.retrieval.types import RetrievalResult, RetrievalSource

__all__ = [
    "ALL_MISS",
    "KNOWLEDGE_MISS",
    "MEMORY_MISS",
    "RetrievalGateway",
    "RetrievalResult",
    "RetrievalSource",
    "get_retrieval_gateway",
]
