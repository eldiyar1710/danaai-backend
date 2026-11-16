# ruff: noqa: RUF001
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.integrations.openai_client import LLMResult, LLMUsage
from app.integrations.voice_audio import SynthesizedAudio
from app.modules.robot.approval import ApprovedDocument, load_approvals, verified_approval
from app.modules.robot.knowledge import Passage, UniversityKnowledge, load_knowledge
from app.modules.robot.router import _request_times, get_robot_service
from app.modules.robot.schemas import RobotReply
from app.modules.robot.semantic import SemanticIndex
from app.modules.robot.service import RobotService, detect_language
from app.robot_server import create_robot_app


class _Embeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _LLM:
    def __init__(self, answer: str, quote: str) -> None:
        self.answer = answer
        self.quote = quote

    async def generate(self, **_: object) -> LLMResult:
        return LLMResult(
            text=json.dumps(
                {"answer": self.answer, "evidence": [{"source": 1, "quote": self.quote}]}
            ),
            model="test",
            response_id="1",
            usage=LLMUsage(1, 1, 0),
        )


class _Audio:
    async def synthesize(self, text: str, **_: object) -> SynthesizedAudio:
        return SynthesizedAudio(b"voice", "audio/mpeg", "mp3", "elevenlabs", "test", "voice")

    async def transcribe(self, **_: object) -> str:
        return "Как поступить?"


_PASSAGE = Passage("4.pdf", 3, "Правила приёма описывают необходимые документы и сроки.")


def _service(answer: str, quote: str) -> RobotService:
    return RobotService(
        settings=Settings(_env_file=None, embedding_dimension=2),
        knowledge=UniversityKnowledge([_PASSAGE]),
        llm=_LLM(answer, quote),  # type: ignore[arg-type]
        audio=_Audio(),  # type: ignore[arg-type]
        semantic_index=SemanticIndex([[1.0, 0.0]]),
        embeddings=_Embeddings(),  # type: ignore[arg-type]
    )


def test_language_follows_the_question() -> None:
    assert detect_language("Білім туралы заң қалай?") == "kk"
    assert detect_language("How does admission work?") == "en"
    assert detect_language("Как поступить в университет?") == "ru"


async def test_answer_uses_verified_quote_and_source() -> None:
    reply = await _service("Нужны документы и соблюдение сроков.", _PASSAGE.text).answer_text(
        "Какие документы нужны для приёма?"
    )
    assert reply.answer.endswith("[1]")
    assert reply.sources[0].file_name == "4.pdf"
    assert "[" not in reply.spoken_text
    assert reply.audio_content_type == "audio/mpeg"


async def test_fabricated_quote_falls_back_without_source() -> None:
    service = _service("Ректор — вымышленный человек.", "В документе так написано.")
    reply = await service.answer_text("Кто ректор?")
    assert reply.sources == []
    assert "нет ответа" in reply.answer


def test_approval_requires_exact_hash_and_pages(tmp_path: Path) -> None:
    document = tmp_path / "23.pdf"
    document.write_bytes(b"approved PDF version")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    manifest = tmp_path / "robot-approval.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "file": "23.pdf",
                        "sha256": digest,
                        "pages": [1],
                        "approved_by": "university owner",
                        "approved_at": "2026-11-16",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    approval = load_approvals(manifest)["23.pdf"]
    assert approval.pages == frozenset({1})
    assert verified_approval(document, approval)
    document.write_bytes(b"changed PDF version")
    assert not verified_approval(document, approval)


def test_repealed_document_cannot_be_approved(tmp_path: Path) -> None:
    manifest = tmp_path / "robot-approval.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "file": "5.pdf",
                        "sha256": "0" * 64,
                        "pages": [1],
                        "approved_by": "owner",
                        "approved_at": "2026-11-16",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_approvals(manifest)


def test_only_approved_pdf_page_is_loaded(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "knowledge" / "25.pdf"
    document = tmp_path / "25.pdf"
    document.write_bytes(source.read_bytes())
    approval = ApprovedDocument(hashlib.sha256(document.read_bytes()).hexdigest(), frozenset({2}))
    knowledge = load_knowledge(
        tmp_path, approvals={"25.pdf": approval}, chunk_size=1200, chunk_overlap=200
    )
    assert knowledge.passages
    assert {passage.page for passage in knowledge.passages} == {2}


def test_robot_route_requires_key_and_rate_limits() -> None:
    settings = Settings(
        _env_file=None, robot_api_key=SecretStr("test-robot-key"), robot_requests_per_minute=1
    )
    app = create_robot_app()

    class _Robot:
        async def answer_text(self, question: str, language: str | None = None) -> RobotReply:
            return RobotReply(
                answer="Ответ по документам университета.",
                spoken_text="Ответ по документам университета.",
                language="ru",
                sources=[],
                audio_base64="YQ==",
                audio_content_type="audio/mpeg",
            )

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_robot_service] = lambda: _Robot()
    _request_times.clear()
    with TestClient(app) as client:
        denied = client.post("/api/v1/robot/text", json={"question": "Кто декан?"})
        headers = {"X-API-Key": "test-robot-key"}
        accepted = client.post(
            "/api/v1/robot/text", json={"question": "Кто декан?"}, headers=headers
        )
        limited = client.post(
            "/api/v1/robot/text", json={"question": "Кто декан?"}, headers=headers
        )
    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert limited.status_code == 429
