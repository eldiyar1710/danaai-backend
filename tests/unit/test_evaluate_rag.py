# ruff: noqa: RUF001

from pathlib import Path

from scripts.evaluate_rag import CaseResult, EvalCase, load_dataset, score_case, summarize

DATASET = Path(__file__).parents[2] / "evaluation" / "datasets" / "tb_starter.jsonl"


def test_starter_dataset_is_valid() -> None:
    cases = load_dataset(DATASET)
    assert len(cases) >= 20
    assert len({case.id for case in cases}) == len(cases)
    assert {case.language for case in cases} == {"ru", "kk"}


def test_instruction_numbers_match_whole_numbers_only() -> None:
    case = EvalCase(id="x", query="q", expected_documents=["10"])
    sources = [
        {"document_title": "Инструкция №109 - Каменщик", "text": ""},
        {"document_title": "Инструкция №10 - РВР на скважинах", "text": ""},
    ]
    assert score_case(case, sources) == (2, True)


def test_expected_text_must_appear_in_a_relevant_source() -> None:
    case = EvalCase(id="x", query="q", expected_documents=["90"], expected_text=["привязь"])
    sources = [
        {"document_title": "Инструкция №13", "text": "страховочная привязь"},
        {"document_title": "Инструкция №90 - на высоте", "text": "каска"},
    ]
    assert score_case(case, sources) == (2, False)


def test_summary_metrics() -> None:
    def result(rank: int | None) -> CaseResult:
        return CaseResult("x", "q", rank, True, False, 10.0, [])

    summary = summarize([result(1), result(3), result(None), result(2)], k=2)
    assert summary["hit_at_1"] == 0.25
    assert summary["hit_at_2"] == 0.5
    assert round(summary["mrr"], 3) == round((1 + 1 / 3 + 1 / 2) / 4, 3)
