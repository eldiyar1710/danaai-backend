from app.modules.conversations.service import ConversationService


def test_assistant_prompt_defines_kurbanali_safety_identity() -> None:
    instructions = ConversationService._instructions("ru")

    assert "Kurbanali (Курбанали)" in instructions
    assert "occupational health and safety" in instructions
    assert "all employees" in instructions
    assert "Answer in Russian" in instructions
    assert "Use only facts from SOURCE CONTEXT" in instructions
