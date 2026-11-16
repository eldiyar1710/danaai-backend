# ruff: noqa: RUF001
from fastapi.testclient import TestClient

from app.integrations.openai_client import LLMResult, LLMUsage
from app.integrations.voice_audio import SynthesizedAudio
from app.modules.robot.knowledge import Passage, UniversityKnowledge
from app.modules.robot.router import get_robot_service, require_robot_key
from app.modules.robot.schemas import RobotReply
from app.modules.robot.service import RobotService, detect_language
from app.robot_server import create_robot_app


def test_search_returns_the_matching_university_page() -> None:
    knowledge = UniversityKnowledge(
        [
            Passage("1.pdf", 2, "Закон об образовании устанавливает уровни образования."),
            Passage("23.pdf", 4, "Декан факультета принимает студентов по расписанию."),
        ]
    )

    found = knowledge.search("Какие уровни образования устанавливает закон?")

    assert found[0].file_name == "1.pdf"
    assert found[0].page == 2

    inflected = UniversityKnowledge(
        [Passage("1.pdf", 5, "В законе об образовании указаны уровни образования.")]
    ).search("Какие уровни образования есть?")
    assert inflected[0].page == 5


def test_language_follows_the_question() -> None:
    assert detect_language("Білім туралы заң қалай?") == "kk"
    assert detect_language("How does admission work?") == "en"
    assert detect_language("Как поступить в университет?") == "ru"


class _LLM:
    async def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int | None = None,
    ) -> LLMResult:
        del instructions, max_output_tokens
        assert "4.pdf" in input_text
        return LLMResult(
            text="Уровни образования указаны в законе [1].",
            model="test",
            response_id="1",
            usage=LLMUsage(1, 1, 0),
        )


class _Audio:
    async def synthesize(self, text: str, **_: object) -> SynthesizedAudio:
        return SynthesizedAudio(b"voice", "audio/mpeg", "mp3", "elevenlabs", "test", "voice")

    async def transcribe(self, **_: object) -> str:
        return "Как поступить?"


async def test_text_answer_uses_only_matching_pages() -> None:
    service = RobotService(
        settings=_settings(),
        knowledge=UniversityKnowledge(
            [Passage("4.pdf", 3, "Правила приёма описывают документы и сроки.")]
        ),
        llm=_LLM(),  # type: ignore[arg-type]
        audio=_Audio(),  # type: ignore[arg-type]
    )

    reply = await service.answer_text("Какие документы нужны для приёма?")

    assert reply.language == "ru"
    assert reply.sources[0].file_name == "4.pdf"
    assert reply.audio_content_type == "audio/mpeg"
    assert "[" not in reply.spoken_text
    assert "Уровни" in reply.answer


def test_robot_text_route_requires_robot_key() -> None:
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

    app.dependency_overrides[get_robot_service] = lambda: _Robot()
    with TestClient(app) as client:
        denied = client.post("/api/v1/robot/text", json={"question": "Кто декан?"})
        app.dependency_overrides[require_robot_key] = lambda: None
        response = client.post("/api/v1/robot/text", json={"question": "Кто декан?"})

    assert denied.status_code == 503
    assert response.status_code == 200
    assert response.json()["answer"] == "Ответ по документам университета."


def _settings() -> object:
    from app.core.config import Settings

    return Settings(_env_file=None, robot_approved_pdfs="4.pdf")
