from typing import Literal

from pydantic import BaseModel, Field


class RobotSource(BaseModel):
    file_name: str
    page: int = Field(ge=1)


class RobotReply(BaseModel):
    answer: str
    spoken_text: str
    language: Literal["kk", "ru", "en"]
    transcript: str | None = None
    sources: list[RobotSource]
    audio_base64: str
    audio_content_type: str


class TextQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["kk", "ru", "en"] | None = None
