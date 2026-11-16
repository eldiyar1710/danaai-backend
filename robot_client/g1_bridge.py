"""Record G1 microphone multicast, ask the university API, and play its reply."""

import argparse
import asyncio
import base64
import io
import ipaddress
import math
import os
import shutil
import socket
import struct
import subprocess
import time
import wave
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

MULTICAST_GROUP = "239.168.123.161"
MULTICAST_PORT = 5555
SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2
APP_NAME = "danaai-university"


def pcm_rms(pcm: bytes) -> float:
    samples = struct.iter_unpack("<h", pcm[: len(pcm) & ~1])
    squares = [sample[0] * sample[0] for sample in samples]
    return math.sqrt(sum(squares) / len(squares)) if squares else 0.0


def pcm_to_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)
    return output.getvalue()


def open_microphone(interface_ipv4: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", MULTICAST_PORT))
    membership = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(interface_ipv4)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    sock.settimeout(1.0)
    return sock


def record_utterance(
    sock: socket.socket,
    *,
    threshold: float = 500.0,
    max_seconds: float = 12.0,
    trailing_silence: float = 1.0,
) -> bytes:
    """Small energy gate; tune threshold on the actual microphone before use."""
    pre_roll: deque[bytes] = deque(maxlen=4)
    pieces: list[bytes] = []
    started: float | None = None
    last_voice: float | None = None
    while True:
        try:
            packet, _ = sock.recvfrom(8192)
        except TimeoutError:
            if started is not None and last_voice is not None:
                if time.monotonic() - last_voice >= trailing_silence:
                    break
            continue
        if not packet:
            continue
        now = time.monotonic()
        loud = pcm_rms(packet) >= threshold
        if started is None:
            pre_roll.append(packet)
            if loud:
                started = now
                last_voice = now
                pieces.extend(pre_roll)
            continue
        pieces.append(packet)
        if loud:
            last_voice = now
        if now - started >= max_seconds:
            break
        if last_voice is not None and now - last_voice >= trailing_silence:
            break
    pcm = b"".join(pieces)
    return pcm_to_wav(pcm) if len(pcm) >= BYTES_PER_SECOND // 2 else b""


async def ask_server(server: str, key: str, wav: bytes, language: str | None) -> tuple[str, bytes]:
    parsed = urlparse(server)
    if parsed.scheme != "https":
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
        except ValueError as exc:
            raise ValueError("Use HTTPS or a robot-network IPv4 address") from exc
        if parsed.scheme != "http" or address not in ipaddress.ip_network("192.168.123.0/24"):
            raise ValueError("Plain HTTP is allowed only on the isolated G1 network")
    data = {"language": language} if language else None
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            server.rstrip("/") + "/api/v1/robot/audio",
            headers={"X-API-Key": key},
            files={"file": ("question.wav", wav, "audio/wav")},
            data=data,
        )
        response.raise_for_status()
        payload = response.json()
    content_type = payload["audio_content_type"]
    if content_type not in {"audio/mpeg", "audio/wav"}:
        raise ValueError("Unexpected response audio type")
    return content_type, base64.b64decode(payload["audio_base64"], validate=True)


def decode_to_pcm(audio: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for G1 playback")
    result = subprocess.run(  # noqa: S603 - fixed argv with audio passed on stdin
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        input=audio,
        capture_output=True,
        check=True,
        timeout=45,
    )
    if not result.stdout or len(result.stdout) % 2:
        raise ValueError("Invalid decoded PCM")
    return result.stdout


def play_pcm(client: object, pcm: bytes) -> None:
    stream_id = str(uuid4())
    try:
        for offset in range(0, len(pcm), 32000):
            result = client.PlayStream(APP_NAME, stream_id, pcm[offset : offset + 32000])  # type: ignore[attr-defined]
            code = result[0] if isinstance(result, tuple) else result
            if code != 0:
                raise RuntimeError(f"Unitree PlayStream failed with code {code}")
            time.sleep(1.0)
    finally:
        client.PlayStop(APP_NAME)  # type: ignore[attr-defined]


def _unitree_client(interface: str) -> object:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # type: ignore[import-not-found]
    from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient  # type: ignore[import-not-found]

    ChannelFactoryInitialize(0, interface)
    client = AudioClient()
    client.SetTimeout(10.0)
    client.Init()
    return client


async def main() -> None:
    parser = argparse.ArgumentParser(description="G1 university audio bridge")
    parser.add_argument("--server", required=True, help="Robot-reachable university API URL")
    parser.add_argument("--interface", help="G1 network interface for Unitree SDK")
    parser.add_argument("--interface-ipv4", help="IPv4 address on the G1 network")
    parser.add_argument("--language", choices=("kk", "ru", "en"))
    parser.add_argument("--input-wav", type=Path, help="Test API without robot hardware")
    parser.add_argument("--output-audio", type=Path, help="Save API output during test")
    args = parser.parse_args()
    key = os.environ.get("ROBOT_API_KEY", "")
    if not key:
        parser.error("ROBOT_API_KEY must be set locally")
    if args.input_wav:
        content_type, audio = await ask_server(
            args.server, key, args.input_wav.read_bytes(), args.language
        )
        if not args.output_audio:
            parser.error("--output-audio is required with --input-wav")
        args.output_audio.write_bytes(audio)
        print(f"Saved {content_type} reply to {args.output_audio}")
        return
    if not args.interface or not args.interface_ipv4:
        parser.error("--interface and --interface-ipv4 are required for live G1 audio")
    client = _unitree_client(args.interface)
    with open_microphone(args.interface_ipv4) as sock:
        while True:
            wav = await asyncio.to_thread(record_utterance, sock)
            if not wav:
                continue
            try:
                _, audio = await ask_server(args.server, key, wav, args.language)
                await asyncio.to_thread(play_pcm, client, decode_to_pcm(audio))
            except (httpx.HTTPError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                print(f"Audio request failed: {type(exc).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
