import json
from pathlib import Path

from app.modules.robot.knowledge import Passage
from app.modules.robot.semantic import SemanticIndex, fingerprint, load_index


class _Embedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


async def test_semantic_search_can_find_passage_without_shared_words() -> None:
    passages = [
        Passage("23.pdf", 1, "Университет басшысы туралы мәлімет."),
        Passage("25.pdf", 2, "Академический отпуск оформляется по заявлению."),
    ]
    index = SemanticIndex([[1.0, 0.0], [0.0, 1.0]])
    found = await index.search(
        "Кто руководит вузом?", passages, _Embedder(), limit=2, min_score=0.4  # type: ignore[arg-type]
    )
    assert [(item.file_name, item.page) for item in found] == [("23.pdf", 1)]


def test_changed_approved_passages_invalidate_index(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    old = [Passage("23.pdf", 1, "Old text")]
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "fingerprint": fingerprint(old),
                "model": "test",
                "dimension": 2,
                "vectors": [[1.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    assert load_index(str(path), fingerprint(old), "test", 2, 1) is not None
    changed = [Passage("23.pdf", 1, "New text")]
    assert load_index(str(path), fingerprint(changed), "test", 2, 1) is None
