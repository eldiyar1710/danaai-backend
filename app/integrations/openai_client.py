from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import Settings


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, model_unavailable: bool = False) -> None:
        super().__init__(message)
        self.model_unavailable = model_unavailable


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    response_id: str
    usage: LLMUsage


class OpenAIResponsesClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _api_key(self) -> str:
        if self.settings.openai_api_key is None:
            raise LLMProviderError("OPENAI_API_KEY is not configured")
        value = self.settings.openai_api_key.get_secret_value().strip()
        if not value:
            raise LLMProviderError("OPENAI_API_KEY is not configured")
        return value

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(str(content["text"]))
        return "".join(parts).strip()

    async def generate(self, *, instructions: str, input_text: str) -> LLMResult:
        models = list(dict.fromkeys([self.settings.llm_model, self.settings.llm_fallback_model]))
        last_error: str | None = None
        for model in models:
            try:
                return await self._generate_with_model(
                    model=model, instructions=instructions, input_text=input_text
                )
            except LLMProviderError as exc:
                last_error = str(exc)
                if not exc.model_unavailable:
                    raise
        raise LLMProviderError(last_error or "OpenAI generation failed")

    async def _generate_with_model(
        self, *, model: str, instructions: str, input_text: str
    ) -> LLMResult:
        url = f"{str(self.settings.openai_base_url).rstrip('/')}/responses"
        body = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "reasoning": {"effort": self.settings.openai_reasoning_effort},
            "max_output_tokens": self.settings.llm_max_output_tokens,
            "store": self.settings.openai_store_responses,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "Content-Type": "application/json",
                        "X-Client-Request-Id": str(uuid4()),
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise LLMProviderError("OpenAI request failed") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("x-request-id", "unknown")
            raise LLMProviderError(
                f"OpenAI returned HTTP {response.status_code} (request_id={request_id})",
                model_unavailable=response.status_code == 404,
            )
        payload = response.json()
        text = self._output_text(payload)
        if not text:
            raise LLMProviderError("OpenAI returned an empty text response")
        usage = payload.get("usage") or {}
        output_details = usage.get("output_tokens_details") or {}
        return LLMResult(
            text=text,
            model=str(payload.get("model") or model),
            response_id=str(payload.get("id") or ""),
            usage=LLMUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                reasoning_tokens=int(output_details.get("reasoning_tokens") or 0),
            ),
        )
