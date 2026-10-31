# Semyzbay Backend

Production-oriented modular FastAPI backend for the Semyzbay occupational-safety assistant.
The repository currently contains the infrastructure foundation and the authentication,
organization, and user-management APIs.

## What is implemented

- FastAPI application with OpenAPI, request IDs, JSON logging, CORS, liveness and readiness.
- Async SQLAlchemy engine and an Alembic initial migration for the complete core data model.
- Async Redis and Qdrant clients plus MinIO connectivity.
- Docker Compose topology for API, worker, PostgreSQL 16, Redis, Qdrant, and MinIO.
- Non-root API/worker images, persistent volumes, health checks, and restart policies.
- Pinned direct dependency locks and unit tests for settings and health behavior.
- Argon2 password hashing, short-lived JWT access tokens, hashed refresh sessions, token
  rotation, logout revocation, and database-backed active-user validation.
- Role-based access control for `super_admin`, `org_admin`, and `user` roles.
- Organization and tenant-scoped user administration with soft user deactivation.
- Tenant-scoped PDF, DOCX, TXT, and Markdown intake with content validation, SHA-256
  version records, private MinIO storage, Celery job tracking, approval, archive, reindex,
  status, version listing, and authenticated streaming download.
- Immutable document-version uploads with independent file metadata, approval-gated active
  version switching, retrying Celery jobs, and coordinated PostgreSQL/MinIO/Qdrant deletion.
- Structured PDF/DOCX/TXT/Markdown extraction, LangChain recursive chunking, multilingual
  dense embeddings, BM25 sparse embeddings, named Qdrant vectors and payload indexes.
- Tenant-filtered approved/active hybrid search using Qdrant RRF fusion.
- Advanced RAG retrieval with query normalization, kk/ru/en language detection,
  configurable reranking, prompt-injection filtering, bounded deduplicated context, and
  deterministic source IDs for citation validation.

Grounded LLM generation, conversations, audit APIs, and speech are not complete yet; they
follow the phase gates in [architecture](docs/architecture.md).

## Local Docker run

```bash
cp .env.example .env
# Replace all change_me values and JWT_SECRET_KEY before any shared deployment.
docker compose up -d --build
docker compose ps
```

If port 8000 is already occupied, set `API_PORT=18000` (and update
`PUBLIC_BASE_URL`) in `.env` before starting.

Then open:

- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`
- `http://localhost:8000/health`
- `http://localhost:8000/health/ready`

The API container applies `alembic upgrade head` before starting. Infrastructure services
are private to the Compose network; only port 8000 is published.

Create the first administrator interactively:

```bash
docker compose exec semyzbay-api python scripts/create_superadmin.py \
  --email admin@example.com --first-name System --last-name Admin
```

Authentication and administration routes are exposed below `/api/v1`:

- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`
- `POST /organizations`, `GET /organizations`, `PATCH /organizations/{organization_id}`
- `POST /users`, `GET /users`, `PATCH /users/{user_id}`, `DELETE /users/{user_id}`
- `POST /documents/upload`, `GET /documents`, `GET /documents/{document_id}`
- `GET /documents/{document_id}/versions`, `/status`, and `/download`
- `POST /documents/{document_id}/versions`
- `POST /documents/{document_id}/approve`, `/archive`, and `/reindex`
- `DELETE /documents/{document_id}` (controlled cross-store deletion)
- `POST /knowledge-base/search`, `GET /knowledge-base/stats`
- `POST /rag/retrieve` (safe retrieval package for the future chat/generation API)
- `POST /chat/messages`, `POST /chat/messages/stream`
- `POST /conversations`, `GET /conversations`
- `GET /conversations/{conversation_id}/messages`

The development defaults use the lightweight FastEmbed multilingual MiniLM embedding model
and deterministic lexical reranking. Set `RERANKER_PROVIDER=fastembed` to enable the
Apache-2.0 multilingual `BAAI/bge-reranker-v2-m3-int8` cross-encoder. Its model artifact is
about 570 MB, so production should pre-bake or persist the FastEmbed cache. The first use of
each configured model downloads its artifacts.

`POST /rag/retrieve` never accepts unapproved or inactive Qdrant points and uses the same
tenant authorization as knowledge-base search. Retrieved text that resembles an instruction
override is excluded by default. Generation code must treat the returned `context` as
untrusted quoted data and validate final-answer citations with the RAG citation validator.

Grounded chat calls the OpenAI Responses API with `store=false`, refuses generation when
approved context is insufficient, validates every `[S#]` citation before returning an answer,
and persists accepted sources alongside the assistant message. The SSE endpoint buffers until
validation completes so ungrounded model output is never streamed to clients.

The former public MinIO Community container registry stopped allowing anonymous pulls in
2026. For reproducible local development, Compose builds the last pinned AGPL Community
release from its official source tag. This archived release receives no security updates;
production must use a supported MinIO AIStor deployment or a reviewed S3-compatible service.

## Native development

Python 3.12 is the supported baseline.

```bash
make install
cp .env.example .env
make test
make lint
```

To run migrations or the API natively, point service hosts in `.env` to `localhost` and
start the dependencies. The databases are deliberately never created using
`Base.metadata.create_all()`.

## Production notes

Use external secret management, TLS termination, immutable image digests, encrypted
backups, private service networking, observability, and tested retention/restore policies.
Do not deploy the example credentials.
