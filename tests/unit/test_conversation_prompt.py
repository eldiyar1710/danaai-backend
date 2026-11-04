# ruff: noqa: RUF001

from app.modules.conversations.service import ConversationService


def test_assistant_prompt_defines_kurbanali_safety_identity() -> None:
    instructions = ConversationService._instructions("ru")

    assert "Kurbanali (Курбанали)" in instructions
    assert "occupational health and safety" in instructions
    assert "all employees" in instructions
    assert "Answer in Russian" in instructions
    assert "Use only facts from SOURCE CONTEXT" in instructions
    assert "Never claim access to live weather" in instructions


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


def test_basic_conversation_receives_fast_localized_answers() -> None:
    assert "всё хорошо" in ConversationService._direct_answer("Как дела?", "ru")
    assert "ауа райы" in ConversationService._direct_answer("Бүгінгі ауа райы қандай?", "kk")
    assert "live weather" in ConversationService._direct_answer("What is the weather today?", "en")
    assert "Курбанали" in ConversationService._direct_answer("Здравствуйте!", "ru")
    assert ConversationService._direct_answer("Какие СИЗ нужны сварщику?", "ru") is None


def test_weather_safety_question_is_not_mistaken_for_small_talk() -> None:
    assert (
        ConversationService._direct_answer(
            "При какой погоде разрешены работы на высоте?", "ru"
        )
        is None
    )
