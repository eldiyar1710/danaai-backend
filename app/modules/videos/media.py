"""Video validation and ffmpeg/ffprobe helpers (blocking; call via asyncio.to_thread)."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
_WEBM_SIGNATURE = b"\x1a\x45\xdf\xa3"
FFMPEG_TIMEOUT_SECONDS = 300


class VideoMediaError(ValueError):
    """The file is not a usable video, or ffmpeg is unavailable."""


@dataclass(frozen=True, slots=True)
class VideoInfo:
    duration_seconds: float
    width: int | None
    height: int | None


def sniff_video(suffix: str, head: bytes) -> bool:
    """Cheap container check on the first bytes before anything is stored."""
    if suffix in {".mp4", ".m4v", ".mov"}:
        return len(head) >= 12 and head[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free"}
    if suffix == ".webm":
        return head.startswith(_WEBM_SIGNATURE)
    return False


def _binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise VideoMediaError(f"{name} is required to process videos but is not installed")
    return binary


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, temp file paths only
            command, check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoMediaError(f"{Path(command[0]).name} timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise VideoMediaError(f"{Path(command[0]).name} failed: {detail[0][:200]}") from exc


def probe(path: Path) -> VideoInfo:
    result = _run(
        [
            _binary("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(result.stdout or b"{}")
    video_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise VideoMediaError("The file contains no video stream")
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise VideoMediaError("Could not determine the video duration")
    stream = video_streams[0]
    return VideoInfo(
        duration_seconds=round(duration, 3),
        width=stream.get("width"),
        height=stream.get("height"),
    )


def make_faststart(source: Path, target: Path) -> bool:
    """Move the MP4 index to the front so playback starts before the download ends."""
    try:
        _run(
            [
                _binary("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(target),
            ]
        )
    except VideoMediaError:
        return False
    return target.is_file() and target.stat().st_size > 0


def make_thumbnail(source: Path, target: Path, duration_seconds: float) -> bool:
    position = min(1.0, duration_seconds / 2)
    try:
        _run(
            [
                _binary("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-ss",
                f"{position:.2f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-2",
                str(target),
            ]
        )
    except VideoMediaError:
        return False
    return target.is_file() and target.stat().st_size > 0
