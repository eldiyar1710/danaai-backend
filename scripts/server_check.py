# ruff: noqa: RUF001, RUF003

"""Post-deploy check of a running Semyzbay API: routes, permissions and real questions.

Read-only for documents, users and organizations. It creates chat conversations (and voice
answers when --audio is given) for the test user, so run it with dedicated test accounts.

Usage::

    CHECK_USER_EMAIL=user@... CHECK_USER_PASSWORD=... \\
    CHECK_ADMIN_EMAIL=orgadmin@... CHECK_ADMIN_PASSWORD=... \\
        python scripts/server_check.py --base-url https://api.danaai.kz --output tmp/check.json

Passwords are read from the environment or prompted, never passed as arguments. The script
prints a PASS/FAIL line per check and every question with the answer, the cited sources and
the latency, and exits with status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

# Questions grouped into conversations; later questions in a group are follow-ups that only
# make sense with the history ("а если …"), so they exercise the standalone-query rewrite.
QUESTIONS: list[list[str]] = [
    ["Какие меры безопасности нужны при работе на высоте?", "А какие СИЗ для этого нужны?"],
    ["Какие требования к каменщику для допуска к работе?", "А если работа на высоте?"],
    ["Безопасные приемы работы газоэлектросварщика", "А при сварке в закрытых ёмкостях?"],
    ["Как оказать первую помощь при поражении электрическим током?"],
    ["Как безопасно накачивать шины?"],
    ["Как безопасно работать с кислородными баллонами?"],
    ["Что должен делать персонал при чрезвычайной ситуации?"],
    ["Как применять стоп-карту?"],
    ["Биіктікте жұмыс істегенде қандай қауіпсіздік шаралары қажет?"],
    ["Жазатайым оқиға кезінде алғашқы көмек қалай көрсетіледі?"],
    ["Как ты думаешь, нужна ли каска при работе на высоте?"],
    ["Какая зарплата у сварщика?"],
]
SMALL_TALK = ["Привет!", "Кто ты?"]


class Checker:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = httpx.Client(base_url=args.base_url, timeout=args.timeout)
        self.prefix = args.api_prefix.rstrip("/")
        self.results: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: Any = "") -> bool:
        self.results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
        mark = "PASS" if ok else "FAIL"
        suffix = f"  | {str(detail)[:200]}" if detail and not ok else ""
        print(f"{mark} {name}{suffix}")
        return bool(ok)

    def url(self, path: str) -> str:
        return f"{self.prefix}{path}"

    def login(self, email: str, password: str) -> dict[str, str] | None:
        response = self.client.post(
            self.url("/auth/login"), json={"email": email, "password": password}
        )
        if response.status_code != 200:
            self.check(f"login {email}", False, f"HTTP {response.status_code}")
            return None
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def get(self, path: str, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return self.client.get(self.url(path), headers=headers, **kw)

    def post(self, path: str, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        return self.client.post(self.url(path), headers=headers, **kw)

    # ------------------------------------------------------------------ checks
    def health(self) -> None:
        self.check("GET /health", self.client.get("/health").status_code == 200)
        ready = self.client.get("/health/ready")
        body = ready.json() if ready.status_code == 200 else {}
        self.check("GET /health/ready", body.get("status") == "ready", ready.text[:200])
        spec = self.client.get("/openapi.json")
        text = spec.text if spec.status_code == 200 else ""
        self.check(
            "deployed version has history-aware chat (standalone_query)",
            "standalone_query" in text,
            "old code is still running" if text else f"HTTP {spec.status_code}",
        )

    def auth(self, user: dict[str, str]) -> None:
        self.check("no token -> 401", self.get("/auth/me").status_code == 401)
        wrong = self.post(
            "/auth/login", json={"email": self.args.user_email, "password": "wrong-password-x"}
        )
        self.check("wrong password -> 401", wrong.status_code == 401)
        me = self.get("/auth/me", user)
        self.check("GET /auth/me", me.status_code == 200, me.text[:120])

    def admin_routes(self, admin: dict[str, str], user: dict[str, str]) -> None:
        docs = self.get("/documents", admin)
        self.check("GET /documents (admin)", docs.status_code == 200, docs.text[:120])
        documents = docs.json() if docs.status_code == 200 else []
        ready = [d for d in documents if d.get("status") == "ready"]
        self.check("documents ready", bool(ready), f"{len(ready)}/{len(documents)} ready")
        failed = [d["title"] for d in documents if d.get("status") == "failed"]
        self.check("no failed documents", not failed, failed[:5])
        if ready:
            doc_id = ready[0]["id"]
            for path in (
                f"/documents/{doc_id}",
                f"/documents/{doc_id}/versions",
                f"/documents/{doc_id}/status",
            ):
                self.check(
                    f"GET {path.replace(doc_id, '{id}')}", self.get(path, admin).status_code == 200
                )
            download = self.get(f"/documents/{doc_id}/download", user)
            self.check(
                "user downloads approved document",
                download.status_code == 200,
                download.status_code,
            )
        self.check("GET /users (admin)", self.get("/users", admin).status_code == 200)
        self.check("user cannot list users -> 403", self.get("/users", user).status_code == 403)
        self.check(
            "user cannot list documents -> 403", self.get("/documents", user).status_code == 403
        )
        self.check(
            "org_admin cannot list organizations -> 403",
            self.get("/organizations", admin).status_code == 403,
        )
        safety = self.get("/safety/employees", admin)
        self.check("GET /safety/employees (admin)", safety.status_code == 200, safety.text[:120])

    def user_routes(self, user: dict[str, str]) -> None:
        stats = self.get("/knowledge-base/stats", user)
        chunks = stats.json().get("active_chunks", 0) if stats.status_code == 200 else 0
        self.check("knowledge base has active chunks", chunks > 0, f"active_chunks={chunks}")
        search = self.post("/knowledge-base/search", user, json={"query": "работа на высоте"})
        self.check(
            "POST /knowledge-base/search",
            search.status_code == 200 and search.json().get("results"),
            search.text[:150],
        )
        rag = self.post("/rag/retrieve", user, json={"query": "работа на высоте"})
        self.check(
            "POST /rag/retrieve",
            rag.status_code == 200 and rag.json().get("sources"),
            rag.text[:150],
        )
        self.check("GET /conversations", self.get("/conversations", user).status_code == 200)
        me = self.get("/safety/employees/me", user)
        self.check(
            "GET /safety/employees/me (200 or 404 without profile)",
            me.status_code in (200, 404),
            me.status_code,
        )
        voices = self.get("/speech/voices", user)
        self.check("GET /speech/voices", voices.status_code == 200, voices.text[:120])

    def ask(self, user: dict[str, str], query: str, conversation_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if conversation_id:
            body["conversation_id"] = conversation_id
        started = time.perf_counter()
        response = self.post("/chat/messages", user, json=body)
        latency = round(time.perf_counter() - started, 2)
        if response.status_code != 200:
            entry = {
                "query": query,
                "error": f"HTTP {response.status_code}",
                "detail": response.text[:300],
                "latency_s": latency,
            }
        else:
            data = response.json()
            entry = {
                "query": query,
                "conversation_id": data["conversation_id"],
                "status": data["generation_status"],
                "standalone_query": data.get("standalone_query"),
                "answer": data["answer"],
                "sources": [
                    {
                        "citation": s["citation_id"],
                        "title": s.get("document_title"),
                        "section": s.get("section_title"),
                        "page": s.get("page_number"),
                    }
                    for s in data.get("sources", [])
                ],
                "citations_valid": data["citation_validation"]["valid"],
                "model": data.get("model"),
                "latency_s": latency,
            }
        self.answers.append(entry)
        return entry

    def questions(self, user: dict[str, str]) -> None:
        for text in SMALL_TALK:
            entry = self.ask(user, text, None)
            self.check(
                f"small talk: {text}",
                entry.get("model") is None and "error" not in entry,
                entry.get("error") or entry.get("model"),
            )
        for group in QUESTIONS:
            conversation_id = None
            for index, text in enumerate(group):
                entry = self.ask(user, text, conversation_id)
                conversation_id = entry.get("conversation_id")
                ok = "error" not in entry and entry["status"] in {
                    "answered",
                    "insufficient_context",
                }
                self.check(f"question: {text[:60]}", ok, entry.get("error") or entry.get("detail"))
                if index > 0 and "error" not in entry:
                    self.check(
                        f"  follow-up rewritten: {text[:40]}",
                        bool(entry.get("standalone_query")),
                        "standalone_query is null",
                    )
        answered = [a for a in self.answers if a.get("status") == "answered" and a.get("model")]
        self.check(
            "answered questions cite sources",
            all(a["sources"] and a["citations_valid"] for a in answered),
        )

    def stream(self, user: dict[str, str]) -> None:
        stages: list[str] = []
        names: list[str] = []
        with self.client.stream(
            "POST",
            self.url("/chat/messages/stream"),
            headers=user,
            json={"query": "Какие СИЗ нужны сварщику?"},
        ) as response:
            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    fields = dict(
                        line.split(": ", 1) for line in block.splitlines() if ": " in line
                    )
                    names.append(fields.get("event", ""))
                    if fields.get("event") == "status":
                        stages.append(json.loads(fields["data"])["stage"])
        self.check("SSE sends status stages", "retrieving" in stages, stages)
        self.check("SSE completes", names[-1:] == ["completed"], names[-3:])

    def voice(self, user: dict[str, str], audio_path: Path) -> None:
        content = audio_path.read_bytes()
        files = {"file": (audio_path.name, content, "application/octet-stream")}
        transcript = self.post("/speech/transcribe", user, files=files)
        self.check("POST /speech/transcribe", transcript.status_code == 200, transcript.text[:200])
        if transcript.status_code == 200:
            print(f"      transcript: {transcript.json()['text']}")
        answer = self.post("/voice/ask", user, files=files)
        self.check("POST /voice/ask", answer.status_code == 200, answer.text[:200])
        if answer.status_code == 200:
            data = answer.json()
            print(f"      voice answer: {data['spoken_text'][:200]}")
            audio = self.client.get(data["audio"]["url"], headers=user)
            self.check(
                "GET voice answer audio",
                audio.status_code == 200 and bool(audio.content),
                audio.status_code,
            )
        tts = self.post("/speech/synthesize", user, json={"text": "Проверка синтеза речи."})
        self.check(
            "POST /speech/synthesize", tts.status_code == 200 and bool(tts.content), tts.status_code
        )


def _secret(name: str, prompt: str) -> str:
    return os.environ.get(name) or getpass.getpass(prompt)


def run(args: argparse.Namespace) -> int:
    checker = Checker(args)
    checker.health()
    user = checker.login(args.user_email, _secret("CHECK_USER_PASSWORD", "User password: "))
    admin = None
    if args.admin_email:
        admin = checker.login(args.admin_email, _secret("CHECK_ADMIN_PASSWORD", "Admin password: "))
    if user is None:
        return 1
    checker.auth(user)
    if admin is not None:
        checker.admin_routes(admin, user)
    checker.user_routes(user)
    checker.questions(user)
    checker.stream(user)
    if args.audio:
        checker.voice(user, Path(args.audio))

    print("\n================ answers ================")
    for entry in checker.answers:
        print(f"\nQ: {entry['query']}")
        if "error" in entry:
            print(f"   ERROR {entry['error']}: {entry['detail']}")
            continue
        if entry.get("standalone_query"):
            print(f"   (search: {entry['standalone_query']})")
        print(f"   [{entry['status']}, {entry['latency_s']} s] {entry['answer']}")
        for source in entry["sources"]:
            print(f"   {source['citation']}: {source['title']} / {source['section'] or '-'}")

    failed = [r for r in checker.results if not r["ok"]]
    print(f"\n{len(checker.results) - len(failed)}/{len(checker.results)} checks passed")
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {"checks": checker.results, "answers": checker.answers},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 1 if failed else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", default=os.environ.get("CHECK_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--user-email", default=os.environ.get("CHECK_USER_EMAIL"))
    parser.add_argument("--admin-email", default=os.environ.get("CHECK_ADMIN_EMAIL"))
    parser.add_argument(
        "--audio", default=None, help="Optional recorded question (wav/mp3/m4a/webm)"
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", default=None, help="Write a JSON report to this path")
    args = parser.parse_args(argv)
    if not args.user_email:
        parser.error("--user-email or CHECK_USER_EMAIL is required")
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
