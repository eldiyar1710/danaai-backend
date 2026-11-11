# ruff: noqa: RUF001
"""Upload the five work-at-height training clips with their cards through the API.

Each card links the clip to the instructions it illustrates (found by number in the
document title) and lists the questions it answers. Clips 1-4 are approved; clip 5
(transfer with two lanyards) stays in review because the approved instructions do not yet
describe that procedure — approve it in the admin UI or with --approve-all once a safety
specialist has signed it off.

Usage::

    SEED_EMAIL=orgadmin@semyzbay.kz python scripts/seed_safety_videos.py \\
        --base-url https://api.danaai.kz --videos-dir TB/videos

The script is idempotent: a card whose title already exists is skipped.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class Card:
    filename: str
    title: str
    description: str
    example_questions: list[str]
    instructions: list[str]
    approve: bool = True
    note: str = ""
    language: str = "ru"


CARDS: list[Card] = [
    Card(
        filename="01_work_at_height_basics.mp4",
        title="Работы на высоте: допуск, лестница, ограждение",
        description=(
            "Работы на высоте от 1,3 м выполняются по наряду-допуску. К работе допускаются "
            "проинструктированные сотрудники после медосмотра и проверки знаний. При работе "
            "с приставной лестницы пояс крепится к неподвижной конструкции, лестницу "
            "страхует второй сотрудник, место работ ограждается."
        ),
        example_questions=[
            "Как правильно проводить работы на высоте?",
            "С какой высоты нужен наряд-допуск?",
            "Кто должен страховать лестницу?",
            "Можно ли работать на приставной лестнице одному?",
            "Биіктіктегі жұмыстарды қалай дұрыс жүргізу керек?",
        ],
        instructions=["90"],
    ),
    Card(
        filename="02_pre_work_checklist.mp4",
        title="Что проверить перед началом работы на высоте",
        description=(
            "Перед началом работ проверить наряд-допуск, удостоверение и задание, "
            "инструктаж, медосмотр и проверку знаний, исправность каски, спецодежды, "
            "привязи, каната, инструмента и средств подмащивания, рабочее место, подходы, "
            "освещение и ограждения. Если нарушение не устранить — сообщить руководителю и "
            "не начинать работу."
        ),
        example_questions=[
            "Что нужно проверить до начала работы на высоте?",
            "Что делать, если перед работой на высоте обнаружено нарушение?",
            "Какие документы нужны для работы на высоте?",
            "Биіктікте жұмыс бастамас бұрын нені тексеру керек?",
        ],
        instructions=["90"],
    ),
    Card(
        filename="03_harness_inspection.mp4",
        title="Проверка страховочной привязи и стропа",
        description=(
            "Перед каждым использованием осмотреть несущие элементы, швы и соединения, "
            "проверить бирку с инвентарным номером и датой очередной проверки. При "
            "разрывах, прожогах, порезах, повреждении амортизатора, заклёпок, коррозии или "
            "неисправных карабинах использовать запрещено. После рывка — вывести из "
            "эксплуатации, самостоятельный ремонт запрещён."
        ),
        example_questions=[
            "Как проверить страховочную привязь и строп?",
            "Можно ли пользоваться поясом после рывка?",
            "Какие повреждения стропа недопустимы?",
            "Зачем бирка на предохранительном поясе?",
            "Сақтандыру белдігін қалай тексеремін?",
        ],
        instructions=["90", "80"],
    ),
    Card(
        filename="04_anchor_points.mp4",
        title="Куда закреплять страховку: анкерная точка",
        description=(
            "Строп закрепляется только за надёжную неподвижную конструкцию. Трубу или "
            "перила можно использовать лишь после подтверждения, что они выдержат нагрузку. "
            "Если точка не подтверждена — уточнить у руководителя работ и использовать "
            "предусмотренную анкерную точку."
        ),
        example_questions=[
            "Куда можно закреплять страховку?",
            "Можно ли закрепить строп за трубу или перила?",
            "Что такое анкерная точка?",
            "Сақтандыру арқанын қайда бекітуге болады?",
        ],
        instructions=["90"],
    ),
    Card(
        filename="05_twin_lanyard_transfer.mp4",
        title="Переход с двумя стропами без потери страховки",
        description=(
            "При системе с двумя стропами сначала закрепить второй строп за проверенную "
            "точку на новом месте и убедиться в надёжности крепления, только затем "
            "отсоединить первый. Выполнять по утверждённой инструкции и с подтверждения "
            "руководителя работ."
        ),
        example_questions=[
            "Как перейти на другое место, не оставаясь без страховки?",
            "Как перестегнуться при работе на высоте?",
            "Как пользоваться двумя стропами?",
        ],
        instructions=["90"],
        approve=False,
        note=(
            "оставлен на проверке: порядок перехода с двумя стропами не описан в "
            "утверждённых инструкциях"
        ),
    ),
]


def _login(client: httpx.Client, prefix: str, email: str, password: str) -> dict[str, str]:
    response = client.post(f"{prefix}/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise SystemExit(f"Login failed: HTTP {response.status_code} {response.text[:200]}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _find_documents(documents: list[dict[str, Any]], numbers: list[str]) -> list[str]:
    found = []
    for number in numbers:
        pattern = re.compile(rf"№\s*{re.escape(number)}(?!\d)")
        matches = [
            doc["id"]
            for doc in documents
            if doc["status"] != "archived" and pattern.search(doc["title"])
        ]
        found.extend(matches[:1])
    return found


def run(args: argparse.Namespace) -> int:
    email = args.email or os.environ.get("SEED_EMAIL") or input("Email: ")
    password = os.environ.get("SEED_PASSWORD") or getpass.getpass("Password: ")
    prefix = args.api_prefix.rstrip("/")
    videos_dir = Path(args.videos_dir)
    params = {"organization_id": args.organization_id} if args.organization_id else None
    org_form = {"organization_id": args.organization_id} if args.organization_id else {}
    failures = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        headers = _login(client, prefix, email, password)
        documents = client.get(f"{prefix}/documents", headers=headers, params=params).json()
        existing = {
            video["title"]: video
            for video in client.get(f"{prefix}/videos", headers=headers, params=params).json()
        }
        for card in CARDS:
            if card.title in existing:
                print(f"SKIP  {card.title} (already exists: {existing[card.title]['status']})")
                continue
            path = videos_dir / card.filename
            if not path.is_file():
                print(f"MISS  {card.title}: file {path} not found")
                failures += 1
                continue
            linked = _find_documents(documents, card.instructions)
            if not linked:
                print(f"WARN  {card.title}: instructions {card.instructions} not uploaded yet")
            # httpx sends list values as repeated multipart fields.
            data: dict[str, Any] = {
                "title": card.title,
                "description": card.description,
                "language": card.language,
                "example_questions": card.example_questions,
                "linked_document_ids": linked,
                **org_form,
            }
            with path.open("rb") as handle:
                response = client.post(
                    f"{prefix}/videos",
                    headers=headers,
                    data=data,
                    files={"file": (path.name, handle, "video/mp4")},
                )
            if response.status_code != 201:
                print(f"FAIL  {card.title}: HTTP {response.status_code} {response.text[:200]}")
                failures += 1
                continue
            video = response.json()
            video = _wait(client, prefix, headers, video["id"], args.job_timeout)
            if video["status"] != "ready":
                print(f"FAIL  {card.title}: {video['status']} {video.get('error_message') or ''}")
                failures += 1
                continue
            if (card.approve or args.approve_all) and linked:
                approved = client.post(f"{prefix}/videos/{video['id']}/approve", headers=headers)
                state = "approved" if approved.status_code == 200 else approved.text[:200]
            else:
                state = f"ready ({card.note or 'not linked to an instruction'})"
            print(f"OK    {card.title}: {state}, {video['duration_seconds']} s")
    return 1 if failures else 0


def _wait(
    client: httpx.Client, prefix: str, headers: dict[str, str], video_id: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    video: dict[str, Any] = {}
    while time.monotonic() < deadline:
        video = client.get(f"{prefix}/videos/{video_id}", headers=headers).json()
        if video["status"] != "processing":
            return video
        time.sleep(2)
    return video


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", default=os.environ.get("SEED_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--email", default=None)
    parser.add_argument("--organization-id", default=os.environ.get("SEED_ORGANIZATION_ID"))
    parser.add_argument("--videos-dir", default="TB/videos")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--job-timeout", type=float, default=600.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
