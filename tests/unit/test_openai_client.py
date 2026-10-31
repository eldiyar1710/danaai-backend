from app.integrations.openai_client import OpenAIResponsesClient


def test_output_text_collects_only_assistant_text() -> None:
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Use PPE "},
                    {"type": "refusal", "refusal": "ignored"},
                    {"type": "output_text", "text": "[S1]."},
                ],
            },
        ]
    }
    assert OpenAIResponsesClient._output_text(payload) == "Use PPE [S1]."


def test_output_text_is_empty_without_message_items() -> None:
    assert OpenAIResponsesClient._output_text({"output": []}) == ""
