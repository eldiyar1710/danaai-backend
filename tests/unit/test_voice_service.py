from app.modules.voice.service import VoiceService


def test_spoken_text_matches_synthesized_text_cleanup() -> None:
    answer = "## **Answer**\nFollow the procedure [S1] and `stay calm`."

    assert VoiceService._spoken_text(answer) == "Answer\nFollow the procedure and stay calm."
