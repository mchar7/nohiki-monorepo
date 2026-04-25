"""Embedding publisher accessor for single-item skill embedding.

Single-item embeddings for newly created skill nodes are published through
the shared EmbeddingPublisher. Vector persistence happens asynchronously
through the ML callback and sink pipeline.
"""

from skill_graph_service.core.embedding import get_skill_embedding_publisher

__all__ = ["get_skill_embedding_publisher"]
