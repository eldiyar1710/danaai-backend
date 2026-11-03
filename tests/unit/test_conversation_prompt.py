from app.modules.conversations.service import ConversationService


def test_assistant_prompt_defines_kurbanali_safety_identity() -> None:
    instructions = ConversationService._instructions("ru")

    assert "Kurbanali (Курбанали)" in instructions
    assert "occupational health and safety" in instructions
    assert "all employees" in instructions
    assert "Answer in Russian" in instructions
    assert "Use only facts from SOURCE CONTEXT" in instructions


def test_identity_questions_receive_localized_kurbanali_introduction() -> None:
    russian = ConversationService._identity_answer(
        "Привет! Как тебя зовут и что ты делаешь в целом?", "ru"
    )
    kazakh = ConversationService._identity_answer("Сен кімсің?", "kk")
    english = ConversationService._identity_answer("Who are you?", "en")

    assert russian is not None and "Меня зовут Курбанали" in russian
    assert kazakh is not None and "Менің атым Курбанали" in kazakh
    assert english is not None and "My name is Kurbanali" in english
    assert ConversationService._identity_answer("Как работать на высоте?", "ru") is None
