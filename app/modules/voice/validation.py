from pathlib import Path

from fastapi import HTTPException

ALLOWED_AUDIO_SUFFIXES = {
    ".flac",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".m4a",
    ".ogg",
    ".wav",
    ".webm",
}
AUDIO_MIME_BY_SUFFIX = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


def validate_audio(filename: str, content: bytes, declared_mime: str | None, max_size: int) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Supported audio formats: FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, WEBM",
        )
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="Audio file is too large")
    expected_mime = AUDIO_MIME_BY_SUFFIX[suffix]
    if declared_mime and declared_mime not in {expected_mime, "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Audio extension and MIME type do not match")
    return expected_mime
