"""Re-run parsing, chunking and indexing for every non-archived document.

Needed after changes to parsing/chunking and after moving to an empty Qdrant volume
(for example the Qdrant 1.15 -> 1.20 upgrade). Vectors are rebuilt from the original files
in MinIO; approval status and active versions in PostgreSQL are kept, so approved documents
become searchable again as soon as their job succeeds.

Usage (an org_admin reindexes its organization; a super_admin passes --organization-id)::

    REINDEX_EMAIL=orgadmin@semyzbay.kz python scripts/reindex_documents.py

Only ``POST /auth/login``, ``GET /documents``, ``POST /documents/{id}/reindex`` and
``GET /documents/{id}/status`` are called. Exits with status 1 if any job fails.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from collections.abc import Sequence
from typing import Any

import httpx

_FINISHED = {"succeeded", "failed", "cancelled"}


def _login(client: httpx.Client, prefix: str, email: str, password: str) -> str:
    response = client.post(f"{prefix}/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise SystemExit(f"Login failed: HTTP {response.status_code} {response.text[:200]}")
    return str(response.json()["access_token"])


def run(args: argparse.Namespace) -> int:
    email = args.email or os.environ.get("REINDEX_EMAIL") or input("Email: ")
    password = os.environ.get("REINDEX_PASSWORD") or getpass.getpass("Password: ")
    prefix = args.api_prefix.rstrip("/")
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        headers = {"Authorization": f"Bearer {_login(client, prefix, email, password)}"}
        params = {"organization_id": args.organization_id} if args.organization_id else None
        response = client.get(f"{prefix}/documents", headers=headers, params=params)
        if response.status_code != 200:
            raise SystemExit(f"Listing documents failed: HTTP {response.status_code}")
        documents = [doc for doc in response.json() if doc["status"] != "archived"]
        print(f"Reindexing {len(documents)} documents")

        jobs: dict[str, dict[str, Any]] = {}
        for index, document in enumerate(documents):
            # Submit in small batches so the worker queue and embedding provider are not
            # flooded; Celery still processes them with its configured concurrency.
            if args.batch_size and index and index % args.batch_size == 0:
                _wait(client, prefix, headers, jobs, args, until_idle=True)
            result = client.post(f"{prefix}/documents/{document['id']}/reindex", headers=headers)
            if result.status_code != 200:
                print(f"SKIP {document['title'][:70]}: HTTP {result.status_code}")
                continue
            jobs[document["id"]] = {"title": document["title"], "status": "pending"}

        _wait(client, prefix, headers, jobs, args, until_idle=True)

    failed = [job for job in jobs.values() if job["status"] != "succeeded"]
    for job in jobs.values():
        mark = "OK  " if job["status"] == "succeeded" else "FAIL"
        detail = f" ({job.get('error')})" if job.get("error") else ""
        print(f"{mark} {job['title'][:80]}{detail}")
    print(f"\n{len(jobs) - len(failed)}/{len(jobs)} succeeded")
    return 1 if failed else 0


def _wait(
    client: httpx.Client,
    prefix: str,
    headers: dict[str, str],
    jobs: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    *,
    until_idle: bool,
) -> None:
    deadline = time.monotonic() + args.job_timeout
    while until_idle and time.monotonic() < deadline:
        pending = [doc_id for doc_id, job in jobs.items() if job["status"] not in _FINISHED]
        if not pending:
            return
        for doc_id in pending:
            status = client.get(f"{prefix}/documents/{doc_id}/status", headers=headers)
            if status.status_code != 200:
                continue
            job = status.json().get("latest_job") or {}
            if job.get("status") in _FINISHED:
                jobs[doc_id]["status"] = job["status"]
                jobs[doc_id]["error"] = job.get("error_message")
        time.sleep(args.poll_interval)
    for job in jobs.values():
        if job["status"] not in _FINISHED:
            job["status"], job["error"] = "timeout", "job did not finish in time"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", default=os.environ.get("REINDEX_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--email", default=None)
    parser.add_argument("--organization-id", default=os.environ.get("REINDEX_ORGANIZATION_ID"))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--job-timeout", type=float, default=1800.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
