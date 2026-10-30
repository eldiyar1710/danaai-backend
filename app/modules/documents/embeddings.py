from functools import lru_cache

from fastembed import SparseTextEmbedding, TextEmbedding


@lru_cache(maxsize=4)
def dense_model(model_name: str) -> TextEmbedding:
    return TextEmbedding(model_name, lazy_load=True)


@lru_cache(maxsize=4)
def sparse_model(model_name: str) -> SparseTextEmbedding:
    return SparseTextEmbedding(model_name, lazy_load=True)
