# ruff: noqa: RUF001

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.modules.videos import service as video_service
from app.modules.videos.media import VideoMediaError, make_thumbnail, probe, sniff_video
from app.modules.videos.models import SafetyVideo, VideoStatus, card_texts
from app.modules.videos.service import VideoMatcher, VideoService, VideoTokens

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_video.mp4"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, embedding_provider="openai", **overrides)


def _video(**fields: Any) -> SafetyVideo:
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "title": "Проверка страховочной привязи",
        "description": "Осмотр швов и бирки перед использованием",
        "example_questions": ["Как проверить привязь?", "Белдікті қалай тексеремін?"],
        "language": "ru",
        "original_filename": "v.mp4",
        "mime_type": "video/mp4",
        "size_bytes": 10,
        "sha256": "0" * 64,
        "minio_path": "x/y/playback.mp4",
        "thumbnail_path": "x/y/thumbnail.jpg",
        "duration_seconds": 10.0,
        "width": 1280,
        "height": 720,
        "status": VideoStatus.APPROVED,
    }
    defaults.update(fields)
    return SafetyVideo(**defaults)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-200", (800, 999)),
        ("bytes=900-5000", (900, 999)),
    ],
)
def test_parse_range(header: str | None, expected: tuple[int, int] | None) -> None:
    assert VideoService.parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5-2", "items=0-1", "bytes=-"])
def test_unsatisfiable_range_is_416(header: str) -> None:
    with pytest.raises(HTTPException) as error:
        VideoService.parse_range(header, 1000)
    assert error.value.status_code == 416
    assert error.value.headers == {"Content-Range": "bytes */1000"}


def test_signed_link_is_bound_to_the_video() -> None:
    tokens = VideoTokens(_settings())
    video = _video()
    user = cast(Any, SimpleNamespace(id=uuid4()))

    stream_url, thumbnail_url, _expires = tokens.urls(video, user)
    token = stream_url.split("token=", 1)[1]

    assert stream_url.startswith(f"/api/v1/videos/{video.id}/stream?token=")
    assert thumbnail_url is not None and thumbnail_url.endswith(token)
    assert tokens.verify(token, video.id)["org"] == str(video.organization_id)
    with pytest.raises(HTTPException) as error:
        tokens.verify(token, uuid4())
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        tokens.verify(token + "x", video.id)


def test_expired_link_is_rejected() -> None:
    tokens = VideoTokens(_settings(video_url_ttl_minutes=1))
    video = _video()
    token, _ = tokens.issue(video, cast(Any, SimpleNamespace(id=uuid4())))
    import jwt

    payload = jwt.decode(token, options={"verify_signature": False})
    payload["exp"] = 1
    expired = jwt.encode(payload, _settings().jwt_secret_key.get_secret_value(), algorithm="HS256")
    with pytest.raises(HTTPException):
        tokens.verify(expired, video.id)


def test_sniff_video_rejects_renamed_files() -> None:
    assert sniff_video(".mp4", FIXTURE.read_bytes()[:64])
    assert sniff_video(".webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 20)
    assert not sniff_video(".mp4", b"%PDF-1.7 not a video at all")
    assert not sniff_video(".webm", FIXTURE.read_bytes()[:64])


def test_card_texts_include_card_and_each_question() -> None:
    texts = card_texts(_video(example_questions=[" Как проверить привязь? ", ""]))
    assert texts == [
        "Проверка страховочной привязи\nОсмотр швов и бирки перед использованием",
        "Как проверить привязь?",
    ]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_probe_and_thumbnail_on_real_clip(tmp_path: Path) -> None:
    info = probe(FIXTURE)
    assert 1.5 < info.duration_seconds < 2.5
    assert info.width == 320
    thumbnail = tmp_path / "thumb.jpg"
    assert make_thumbnail(FIXTURE, thumbnail, info.duration_seconds)
    assert thumbnail.read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_probe_rejects_non_video(tmp_path: Path) -> None:
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
    with pytest.raises(VideoMediaError):
        probe(fake)


class _Result:
    def __init__(self, rows: list[tuple[SafetyVideo, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[SafetyVideo, Any]]:
        return self.rows


def _matcher(rows: list[tuple[SafetyVideo, Any]], **settings: Any) -> VideoMatcher:
    async def execute(_query: Any) -> _Result:
        return _Result(rows)

    session = SimpleNamespace(execute=execute)
    return VideoMatcher(cast(Any, session), _settings(**settings))


async def test_matcher_picks_closest_video_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = uuid4()
    model = "openai:text-embedding-3-large"
    close = _video(title="close", embeddings=[[1.0, 0.0], [0.9, 0.1]], embedding_model=model)
    far = _video(title="far", embeddings=[[0.0, 1.0]], embedding_model=model)
    stale = _video(title="stale", embeddings=[[1.0, 0.0]], embedding_model="other:model")

    async def fake_embed(settings: Settings, texts: list[str], *, query: bool) -> Any:
        return [[1.0, 0.05]]

    monkeypatch.setattr(video_service, "embed_dense", fake_embed)
    matcher = _matcher([(close, doc), (far, doc), (stale, doc)])
    actor = cast(Any, SimpleNamespace(id=uuid4()))

    suggestions = await matcher.suggest(
        actor, close.organization_id, "Как проверить привязь?", [doc]
    )

    assert [s.title for s in suggestions] == ["close"]
    assert suggestions[0].score > 0.99
    assert suggestions[0].linked_document_ids == [doc]
    assert suggestions[0].stream_url.startswith(f"/api/v1/videos/{close.id}/stream?token=")


async def test_matcher_needs_cited_documents_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = _video(embeddings=[[1.0, 0.0]], embedding_model="openai:text-embedding-3-large")
    actor = cast(Any, SimpleNamespace(id=uuid4()))
    assert await _matcher([(video, uuid4())]).suggest(actor, uuid4(), "q", []) == []

    async def broken_embed(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(video_service, "embed_dense", broken_embed)
    assert await _matcher([(video, uuid4())]).suggest(actor, uuid4(), "q", [uuid4()]) == []


async def test_matcher_respects_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = uuid4()
    video = _video(embeddings=[[1.0, 0.0]], embedding_model="openai:text-embedding-3-large")

    async def orthogonal(settings: Settings, texts: list[str], *, query: bool) -> Any:
        return [[0.0, 1.0]]

    monkeypatch.setattr(video_service, "embed_dense", orthogonal)
    actor = cast(Any, SimpleNamespace(id=uuid4()))
    assert await _matcher([(video, doc)]).suggest(actor, uuid4(), "q", [doc]) == []
