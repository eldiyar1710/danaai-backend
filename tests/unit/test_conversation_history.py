# ruff: noqa: RUF001

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import get_current_user
from app.integrations.openai_client import LLMProviderError, LLMResult, LLMUsage
from app.modules.conversations import router as conversations_router
from app.modules.conversations.models import (
    Conversation,
    GenerationStatus,
    Message,
    MessageRole,
)
from app.modules.conversations.schemas import ChatRequest
from app.modules.conversations.service import ConversationService
from app.modules.rag.schemas import RAGRetrieveRequest, RAGRetrieveResponse, RAGSource


class FakeRepository:
    def __init__(self, conversation: Conversation, history: list[Message]) -> None:
        self.conversation = conversation
        self.history = history
        self.added: list[Message] = []
        self.history_limit: int | None = None

    async def get(self, conversation_id: UUID) -> Conversation | None:
        return self.conversation if conversation_id == self.conversation.id else None

    async def create(self, conversation: Conversation) -> Conversation:
        conversation.id = uuid4()
        return conversation

    async def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        self.history_limit = limit
        return self.history[-limit:]

    async def add_message(self, message: Message) -> Message:
        message.id = uuid4()
        self.added.append(message)
        return message

    def add_sources(self, sources: list[Any]) -> None:
        return None


def _source() -> RAGSource:
    return RAGSource(
        citation_id="S1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        text="При работе на высоте применяется страховочная привязь.",
        retrieval_score=0.9,
        rerank_score=0.9,
    )


def _retrieval(query: str) -> RAGRetrieveResponse:
    return RAGRetrieveResponse(
        normalized_query=query,
        detected_language="ru",
        response_language="ru",
        insufficient_context=False,
        context="[S1] При работе на высоте применяется страховочная привязь.",
        sources=[_source()],
        excluded_suspicious_chunks=0,
        warnings=[],
    )


def _llm_result(text: str) -> LLMResult:
    return LLMResult(
        text=text,
        model="test-model",
        response_id="r",
        usage=LLMUsage(input_tokens=10, output_tokens=5, reasoning_tokens=0),
    )


def _message(role: MessageRole, content: str, status: GenerationStatus) -> Message:
    return Message(
        conversation_id=uuid4(),
        role=role,
        content=content,
        language="ru",
        audio_path=None,
        generation_status=status,
    )


def _build(
    history: list[Message], llm_outputs: list[Any], **settings: Any
) -> tuple[ConversationService, FakeRepository, AsyncMock, AsyncMock, Any]:
    tenant_id = uuid4()
    actor = SimpleNamespace(id=uuid4(), organization_id=tenant_id)
    conversation = Conversation(
        organization_id=tenant_id, user_id=actor.id, title="t", language="ru"
    )
    conversation.id = uuid4()
    rag = SimpleNamespace(
        settings=Settings(_env_file=None, **settings),
        knowledge_base=SimpleNamespace(tenant=Mock(return_value=tenant_id)),
        retrieve=AsyncMock(side_effect=lambda _actor, request: _retrieval(request.query)),
    )
    llm = SimpleNamespace(generate=AsyncMock(side_effect=llm_outputs))
    session = SimpleNamespace(commit=AsyncMock())
    service = ConversationService(cast(Any, session), cast(Any, rag), cast(Any, llm))
    repository = FakeRepository(conversation, history)
    service.repository = cast(Any, repository)
    return service, repository, rag.retrieve, llm.generate, actor


@pytest.mark.parametrize(
    "query",
    [
        "Как ты думаешь, нужна ли каска при работе на высоте?",
        "How can you help me with ladder safety?",
        "Что с погодой делать при грозе на буровой?",
        "Спасибо, а что делать при пожаре?",
        "Ауа райы қандай болғанда биіктікте жұмыс істеуге болады?",
        "Who are you allowed to send up the scaffold without a permit?",
    ],
)
def test_safety_questions_are_not_swallowed_by_small_talk(query: str) -> None:
    assert ConversationService._direct_answer(query, "ru") is None


@pytest.mark.parametrize(
    "query",
    [
        "Привет, как дела, кто ты?",
        "Как ты?",
        "Добрый день! Как тебя зовут?",
        "Спасибо большое!",
        "Бүгінгі ауа райы қандай?",
        "Hello! What is your name?",
    ],
)
def test_pure_small_talk_still_gets_a_fast_answer(query: str) -> None:
    assert ConversationService._direct_answer(query, "ru") is not None


async def test_follow_up_question_is_rewritten_with_history_before_retrieval() -> None:
    history = [
        _message(MessageRole.USER, "Какие СИЗ нужны электромонтёру?", GenerationStatus.ANSWERED),
        _message(
            MessageRole.ASSISTANT,
            "Диэлектрические перчатки и боты [S1].",
            GenerationStatus.ANSWERED,
        ),
    ]
    service, repository, retrieve, generate, actor = _build(
        history,
        [
            _llm_result("«Какие СИЗ нужны электромонтёру при работе на высоте?»"),
            _llm_result("Нужна страховочная привязь [S1]."),
        ],
    )

    response = await service.send(
        actor,
        ChatRequest(query="А если на высоте?", conversation_id=repository.conversation.id),
    )

    retrieval_request = cast(RAGRetrieveRequest, retrieve.await_args.args[1])
    assert retrieval_request.query == "Какие СИЗ нужны электромонтёру при работе на высоте?"
    assert response.standalone_query == retrieval_request.query
    assert response.generation_status == "answered"
    assert response.usage.input_tokens == 20

    answer_call = generate.await_args_list[1].kwargs
    assert "CONVERSATION HISTORY" in answer_call["input_text"]
    assert "USER QUESTION:\nА если на высоте?" in answer_call["input_text"]
    # Old [S#] markers must not leak into the history and collide with current sources.
    assert "боты [S1]" not in answer_call["input_text"]
    assert repository.history_limit == 6
    # The stored user message keeps what the employee actually asked.
    assert repository.added[0].content == "А если на высоте?"


async def test_failed_history_turns_are_ignored() -> None:
    history = [
        _message(MessageRole.USER, "Что такое наряд-допуск?", GenerationStatus.ANSWERED),
        _message(MessageRole.ASSISTANT, "Generation failed", GenerationStatus.FAILED),
    ]
    service, repository, _retrieve, generate, actor = _build(
        history,
        [_llm_result("Что такое наряд-допуск для работ на высоте?"), _llm_result("Ответ [S1].")],
    )

    await service.send(
        actor,
        ChatRequest(query="А на высоте?", conversation_id=repository.conversation.id),
    )

    rewrite_input = generate.await_args_list[0].kwargs["input_text"]
    assert "User: Что такое наряд-допуск?" in rewrite_input
    assert "Generation failed" not in rewrite_input


async def test_new_conversation_skips_rewrite() -> None:
    service, _repository, retrieve, generate, actor = _build(
        [], [_llm_result("Нужна страховочная привязь [S1].")]
    )

    response = await service.send(actor, ChatRequest(query="Какие СИЗ нужны на высоте?"))

    assert generate.await_count == 1
    assert cast(RAGRetrieveRequest, retrieve.await_args.args[1]).query == (
        "Какие СИЗ нужны на высоте?"
    )
    assert response.standalone_query is None


async def test_rewrite_failure_falls_back_to_original_question() -> None:
    history = [_message(MessageRole.USER, "Про сварку", GenerationStatus.ANSWERED)]
    service, repository, retrieve, _generate, actor = _build(
        history,
        [LLMProviderError("boom"), _llm_result("Ответ [S1].")],
    )

    response = await service.send(
        actor, ChatRequest(query="А в ёмкостях?", conversation_id=repository.conversation.id)
    )

    assert cast(RAGRetrieveRequest, retrieve.await_args.args[1]).query == "А в ёмкостях?"
    assert response.generation_status == "answered"


async def test_rewrite_can_be_disabled() -> None:
    history = [_message(MessageRole.USER, "Про сварку", GenerationStatus.ANSWERED)]
    service, repository, _retrieve, generate, actor = _build(
        history, [_llm_result("Ответ [S1].")], chat_query_rewrite=False
    )

    await service.send(
        actor, ChatRequest(query="А в ёмкостях?", conversation_id=repository.conversation.id)
    )

    assert generate.await_count == 1
    assert "CONVERSATION HISTORY" in generate.await_args.kwargs["input_text"]


async def test_progress_stages_are_reported_in_order() -> None:
    history = [_message(MessageRole.USER, "Про сварку", GenerationStatus.ANSWERED)]
    service, repository, _retrieve, _generate, actor = _build(
        history, [_llm_result("Сварка в ёмкостях"), _llm_result("Ответ [S1].")]
    )
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    await service.send(
        actor,
        ChatRequest(query="А в ёмкостях?", conversation_id=repository.conversation.id),
        on_stage=on_stage,
    )

    assert stages == ["rewriting", "retrieving", "generating", "validating"]


def _sse_events(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def _stream_client(send: Any) -> TestClient:
    app = FastAPI()
    app.include_router(conversations_router.router)
    fake = SimpleNamespace(send=send)
    app.dependency_overrides[conversations_router.service] = lambda: fake
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    return TestClient(app)


def test_stream_emits_status_events_before_the_answer() -> None:
    service, _repository, _retrieve, _generate, _actor = _build(
        [], [_llm_result("Нужна страховочная привязь [S1].")]
    )

    async def send(actor: Any, data: ChatRequest, *, on_stage: Any) -> Any:
        return await service.send(_actor, data, on_stage=on_stage)

    response = _stream_client(send).post(
        "/chat/messages/stream", json={"query": "Какие СИЗ нужны на высоте?"}
    )

    events = _sse_events(response.text)
    names = [name for name, _ in events]
    assert names[:3] == ["status", "status", "status"]
    assert [payload["stage"] for name, payload in events if name == "status"] == [
        "retrieving",
        "generating",
        "validating",
    ]
    assert names[3] == "metadata"
    assert names[-1] == "completed"
    text = "".join(payload["delta"] for name, payload in events if name == "text_delta")
    assert text == "Нужна страховочная привязь [S1]."


def test_stream_reports_errors_as_event() -> None:
    async def send(actor: Any, data: ChatRequest, *, on_stage: Any) -> Any:
        await on_stage("retrieving")
        raise HTTPException(status_code=403, detail="Conversation access denied")

    response = _stream_client(send).post("/chat/messages/stream", json={"query": "Вопрос"})

    assert _sse_events(response.text) == [
        ("status", {"stage": "retrieving"}),
        ("error", {"status_code": 403, "detail": "Conversation access denied"}),
    ]


async def test_answer_includes_videos_for_cited_documents_only() -> None:
    service, _repository, _retrieve, _generate, actor = _build(
        [], [_llm_result("Нужна страховочная привязь [S1].")]
    )
    calls: list[tuple[str, list[UUID]]] = []

    class FakeMatcher:
        async def suggest(
            self, _actor: Any, _org: UUID, query: str, cited: list[UUID]
        ) -> list[Any]:
            calls.append((query, cited))
            return []

    service.videos = cast(Any, FakeMatcher())
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    response = await service.send(
        actor, ChatRequest(query="Какие СИЗ нужны на высоте?"), on_stage=on_stage
    )

    assert response.videos == []
    assert len(calls) == 1
    assert calls[0][0] == "Какие СИЗ нужны на высоте?"
    assert calls[0][1] == [response.sources[0].document_id]
    assert stages[-1] == "matching_videos"


async def test_no_video_lookup_without_grounded_answer() -> None:
    service, _repository, _retrieve, _generate, actor = _build(
        [], [_llm_result("Ответ без ссылок.")]
    )
    called = False

    class FakeMatcher:
        async def suggest(self, *_args: Any) -> list[Any]:
            nonlocal called
            called = True
            return []

    service.videos = cast(Any, FakeMatcher())
    response = await service.send(actor, ChatRequest(query="Какие СИЗ нужны на высоте?"))

    assert response.generation_status == "insufficient_context"
    assert called is False
