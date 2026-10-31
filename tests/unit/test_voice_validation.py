import pytest
from fastapi import HTTPException

from app.modules.voice.validation import validate_audio


def test_wav_audio_is_accepted() -> None:
    assert validate_audio("question.wav", b"RIFFdata", "audio/wav", 1024) == "audio/wav"


@pytest.mark.parametrize(
    ("filename", "content", "mime", "max_size", "status_code"),
    [
        ("question.exe", b"data", "application/octet-stream", 1024, 415),
        ("question.wav", b"", "audio/wav", 1024, 422),
        ("question.wav", b"too-large", "audio/wav", 2, 413),
        ("question.wav", b"data", "audio/mpeg", 1024, 415),
    ],
)
def test_invalid_audio_is_rejected(
    filename: str, content: bytes, mime: str, max_size: int, status_code: int
) -> None:
    with pytest.raises(HTTPException) as error:
        validate_audio(filename, content, mime, max_size)
    assert error.value.status_code == status_code
