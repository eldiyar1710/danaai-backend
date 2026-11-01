from types import SimpleNamespace

from app.core.config import Settings
from app.integrations.openai_client import LLMProviderError
from app.modules.rag.query_expansion import QueryExpander


class TranslationClient:
    def __init__(self, text: str = "", error: bool = False) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    async def generate(self, *, instructions: str, input_text: str) -> object:
        self.calls += 1
        if self.error:
            raise LLMProviderError("translation unavailable")
        return SimpleNamespace(text=self.text)


async def test_kazakh_query_is_expanded_with_russian_translation() -> None:
    client = TranslationClient("Кому необходимо сообщить при несчастном случае?")
    result = await QueryExpander(Settings(), client).expand(
        "Жазатайым оқиға туралы кімге хабарлау қажет?", "kk"
    )
    assert result.queries == [
        "Жазатайым оқиға туралы кімге хабарлау қажет?",
        "Кому необходимо сообщить при несчастном случае?",
    ]
    assert result.warning is None


async def test_non_kazakh_query_is_not_sent_for_translation() -> None:
    client = TranslationClient("unused")
    result = await QueryExpander(Settings(), client).expand("Что делать при пожаре?", "ru")
    assert result.queries == ["Что делать при пожаре?"]
    assert client.calls == 0


async def test_translation_failure_falls_back_to_original_query() -> None:
    client = TranslationClient(error=True)
    result = await QueryExpander(Settings(), client).expand(
        "Өрт кезінде не істеу керек?", "kk"
    )
    assert result.queries == ["Өрт кезінде не істеу керек?"]
    assert result.warning is not None
