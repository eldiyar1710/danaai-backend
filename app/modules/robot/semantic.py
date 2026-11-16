"""Checksum-bound semantic index for the reviewed university pages."""

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings
from app.integrations.openai_embeddings import OpenAIEmbeddingsClient
from app.modules.robot.knowledge import Passage, UniversityKnowledge


def fingerprint(passages: list[Passage]) -> str:
    digest = hashlib.sha256()
    for passage in passages:
        digest.update(f"{passage.file_name}\0{passage.page}\0{passage.text}\0".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class SemanticIndex:
    vectors: list[list[float]]

    async def search(
        self,
        question: str,
        passages: list[Passage],
        embeddings: OpenAIEmbeddingsClient,
        *,
        limit: int,
        min_score: float,
    ) -> list[Passage]:
        query = (await embeddings.embed([question]))[0]
        query_norm = math.sqrt(sum(value * value for value in query))
        if query_norm == 0:
            return []
        scored: list[tuple[float, int]] = []
        for index, vector in enumerate(self.vectors):
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                continue
            score = sum(a * b for a, b in zip(query, vector, strict=True)) / (query_norm * norm)
            if score >= min_score:
                scored.append((score, index))
        scored.sort(reverse=True)
        return [passages[index] for _, index in scored[:limit]]


async def build_index(settings: Settings, knowledge: UniversityKnowledge, output: Path) -> int:
    if not knowledge.passages:
        raise ValueError("No approved passages to index")
    vectors = await OpenAIEmbeddingsClient(settings).embed([p.text for p in knowledge.passages])
    payload = {
        "version": 1,
        "fingerprint": fingerprint(knowledge.passages),
        "model": settings.embedding_model,
        "dimension": settings.embedding_dimension,
        "vectors": vectors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(output)
    return len(vectors)


@lru_cache(maxsize=2)
def load_index(
    path: str, expected_fingerprint: str, model: str, dimension: int, passage_count: int
) -> SemanticIndex | None:
    file = Path(path)
    if not file.is_file():
        return None
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
        vectors = payload["vectors"]
        if (
            payload.get("version") != 1
            or payload.get("fingerprint") != expected_fingerprint
            or payload.get("model") != model
            or payload.get("dimension") != dimension
            or not isinstance(vectors, list)
            or len(vectors) != passage_count
            or any(not isinstance(v, list) or len(v) != dimension for v in vectors)
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(value)
                for vector in vectors
                for value in vector
            )
        ):
            return None
        return SemanticIndex(vectors)
    except (OSError, ValueError, KeyError, TypeError):
        return None
