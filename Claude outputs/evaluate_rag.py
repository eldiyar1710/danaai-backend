"""Retrieval quality evaluation against a running Semyzbay API.

Each dataset line is a JSON object::

    {"id": "ru-height-01", "query": "...", "expected_documents": ["90"],
     "expected_text": ["страховочн"], "language": "ru"}

``expected_documents`` are instruction numbers or title fragments; a retrieved source counts
as relevant when its ``document_title`` contains one of them (numbers are matched as whole
numbers, so "10" does not match "109"). ``expected_text`` is optional: when given, at least
one fragment must also appear in a relevant source text.

Usage::

    EVAL_EMAIL=orgadmin@semyzbay.kz EVAL_PASSWORD=... \\
        python scripts/evaluate_rag.py --dataset evaluation/datasets/tb_starter.jsonl

The script calls ``POST /auth/login`` and ``POST /rag/retrieve`` only, so it never spends
LLM generation tokens. It exits with status 1 when hit@k is below ``--min-hit-rate``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class EvalCase:
    id: str
    query: str
    expected_documents: list[str]
    expected_text: list[str] = field(default_factory=list)
    language: str | None = None


@dataclass(frozen=True)
class CaseResult:
    id: str
    query: str
    rank: int | None
    text_found: bool
    insufficient_context: bool
    latency_ms: float
    top_titles: list[str]


def load_dataset(path: Path) -> list[EvalCase]:
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
            cases.append(
                EvalCase(
                    id=str(raw["id"]),
                    query=str(raw["query"]),
                    expected_documents=[str(item) for item in raw["expected_documents"]],
                    expected_text=[str(item) for item in raw.get("expected_text", [])],
                    language=raw.get("language"),
                )
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"{path}:{number}: invalid evaluation case ({exc})") from exc
    if not cases:
        raise SystemExit(f"{path}: dataset is empty")
    return cases


def _matches_document(title: str | None, expected: Sequence[str]) -> bool:
    if not title:
        return False
    lowered = title.casefold()
    for fragment in expected:
        if fragment.isdigit():
            if re.search(rf"(?<!\d){re.escape(fragment)}(?!\d)", lowered):
                return True
        elif fragment.casefold() in lowered:
            return True
    return False


def score_case(case: EvalCase, sources: Sequence[dict[str, Any]]) -> tuple[int | None, bool]:
    """Return the 1-based rank of the first relevant source and whether text matched."""
    rank: int | None = None
    text_found = not case.expected_text
    for index, source in enumerate(sources, start=1):
        if not _matches_document(source.get("document_title"), case.expected_documents):
            continue
        if rank is None:
            rank = index
        text = str(source.get("text", "")).casefold()
        if any(fragment.casefold() in text for fragment in case.expected_text):
            text_found = True
    return rank, text_found


def summarize(results: Sequence[CaseResult], k: int) -> dict[str, float]:
    total = len(results)
    hits_at_1 = sum(result.rank == 1 for result in results)
    hits_at_k = sum(result.rank is not None and result.rank <= k for result in results)
    reciprocal = sum(1.0 / result.rank for result in results if result.rank)
    latencies = [result.latency_ms for result in results]
    return {
        "cases": float(total),
        "hit_at_1": hits_at_1 / total,
        f"hit_at_{k}": hits_at_k / total,
        "mrr": reciprocal / total,
        "text_match_rate": sum(result.text_found for result in results) / total,
        "insufficient_context_rate": sum(r.insufficient_context for r in results) / total,
        "latency_p50_ms": statistics.median(latencies),
        "latency_max_ms": max(latencies),
    }


def _login(client: httpx.Client, prefix: str, email: str, password: str) -> str:
    response = client.post(f"{prefix}/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise SystemExit(f"Login failed: HTTP {response.status_code} {response.text[:200]}")
    return str(response.json()["access_token"])


def run(args: argparse.Namespace) -> int:
    cases = load_dataset(Path(args.dataset))
    email = args.email or os.environ.get("EVAL_EMAIL") or input("Email: ")
    password = os.environ.get("EVAL_PASSWORD") or getpass.getpass("Password: ")
    prefix = args.api_prefix.rstrip("/")
    results: list[CaseResult] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        token = _login(client, prefix, email, password)
        headers = {"Authorization": f"Bearer {token}"}
        for case in cases:
            body: dict[str, Any] = {"query": case.query}
            if args.organization_id:
                body["organization_id"] = args.organization_id
            started = time.perf_counter()
            response = client.post(f"{prefix}/rag/retrieve", json=body, headers=headers)
            latency = (time.perf_counter() - started) * 1000
            if response.status_code != 200:
                raise SystemExit(
                    f"{case.id}: /rag/retrieve returned HTTP {response.status_code} "
                    f"{response.text[:200]}"
                )
            payload = response.json()
            sources = payload.get("sources", [])
            rank, text_found = score_case(case, sources)
            results.append(
                CaseResult(
                    id=case.id,
                    query=case.query,
                    rank=rank,
                    text_found=text_found,
                    insufficient_context=bool(payload.get("insufficient_context")),
                    latency_ms=round(latency, 1),
                    top_titles=[str(s.get("document_title")) for s in sources[:3]],
                )
            )

    summary = summarize(results, args.k)
    for result in results:
        mark = "OK  " if result.rank is not None and result.rank <= args.k else "MISS"
        rank_label = str(result.rank) if result.rank is not None else "-"
        print(f"{mark} rank={rank_label:<2} {result.id:<22} {result.query[:70]}")
        if mark == "MISS":
            print(f"      top: {result.top_titles}")
    print()
    for name, value in summary.items():
        formatted = f"{value:.0f}" if name == "cases" or name.endswith("_ms") else f"{value:.3f}"
        print(f"{name:<28}{formatted}")

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {"summary": summary, "results": [asdict(result) for result in results]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if summary[f"hit_at_{args.k}"] >= args.min_hit_rate else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", default="evaluation/datasets/tb_starter.jsonl")
    parser.add_argument(
        "--base-url", default=os.environ.get("EVAL_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--email", default=None)
    parser.add_argument("--organization-id", default=os.environ.get("EVAL_ORGANIZATION_ID"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-hit-rate", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", default=None, help="Write a JSON report to this path")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
