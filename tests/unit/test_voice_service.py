from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.core.config import Settings
from app.integrations.voice_audio import SynthesizedAudio
from app.modules.conversations.schemas import ChatResponse, TokenUsage
from app.modules.rag.schemas import CitationValidation
from app.modules.voice.service import VoiceService


def test_spoken_text_matches_synthesized_text_cleanup() -> None:
    answer = "## **Answer**\nFollow the procedure [S1] and `stay calm`."

    assert VoiceService._spoken_text(answer) == "Answer\nFollow the procedure and stay calm."


async def test_selected_kazakh_language_is_forwarded_to_transcription() -> None:
    tenant_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    audio = SimpleNamespace(
        transcribe=AsyncMock(return_value="Қалыңыз қалай?"),
        synthesize=AsyncMock(
            return_value=SynthesizedAudio(
                content=b"mp3",
                content_type="audio/mpeg",
                extension="mp3",
                provider="elevenlabs",
                model="eleven_v4_turbo",
                voice="voice-id",
            )
        ),
    )
    conversations = SimpleNamespace(
        rag=SimpleNamespace(
            knowledge_base=SimpleNamespace(tenant=Mock(return_value=tenant_id))
        ),
        send=AsyncMock(
            return_value=ChatResponse(
                conversation_id=conversation_id,
                message_id=message_id,
                answer="Жақсы, рақмет!",
                language="kk",
                generation_status="answered",
                model=None,
                usage=TokenUsage(input_tokens=0, output_tokens=0, reasoning_tokens=0),
                sources=[],
                citation_validation=CitationValidation(
                    valid=True,
                    citations=[],
                    unknown_citations=[],
                    missing_citations=False,
                ),
            )
        ),
        attach_audio=AsyncMock(),
    )
    service = VoiceService(
        Settings(_env_file=None),
        Mock(),
        cast(Any, conversations),
        cast(Any, audio),
    )
    service._put = AsyncMock()  # type: ignore[method-assign]

    await service.ask(
        Mock(id=uuid4()),
        filename="question.webm",
        content=b"audio",
        declared_mime="audio/webm",
        conversation_id=None,
        organization_id=None,
        response_language="kk",
    )

    audio.transcribe.assert_awaited_once_with(
        filename="question.webm",
        content=b"audio",
        content_type="audio/webm",
        language="kk",
    )
