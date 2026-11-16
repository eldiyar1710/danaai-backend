# Semyzbay Backend

## University robot prototype

The university PDFs and robot API live in this repository under `knowledge/` and
`app/modules/robot/`. This is separate from the Semyzbay occupational-safety
document store. Run `uvicorn app.robot_server:app --host 127.0.0.1 --port 18000`
for an isolated university API. Its OpenAPI schema is at
`http://127.0.0.1:18000/openapi.json`, with `POST /api/v1/robot/text` and
`POST /api/v1/robot/audio`. Both routes require `X-API-Key` matching
`ROBOT_API_KEY`; the service fails closed if the key is unset. Set
`KNOWLEDGE_DIR` to the absolute path of the PDF folder and explicitly list
reviewed files in `ROBOT_APPROVED_PDFS` (comma-separated, for example
`23.pdf,25.pdf`). `5.pdf` and the catalog are always excluded. Answers without
valid numbered citations fall back to an uncertainty response.

The API accepts uploaded microphone recordings and returns base64 audio from
ElevenLabs or the configured fallback. It does not yet capture G1 microphone
multicast or call Unitree AudioClient to play the reply. Those adapters require
access to the actual robot and its audio API. The lexical PDF search and source
review gate are a prototype; evaluate Kazakh/Russian retrieval and approve
individual documents before public use.

Production-oriented modular FastAPI backend for the Semyzbay occupational-safety assistant
(DanaAI, assistant persona "Kurbanali"). It answers employees' safety questions in Kazakh,
Russian, and English, by text or voice, strictly from approved organization documents with
validated citations, and tracks employee safety training and work clearances.

Frontend integration guide: [docs/frontend-api-guide.md](docs/frontend-api-guide.md).

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
- Five-stage employee safety training with profession-specific work scopes, granular
  clearance blocking, expiration handling, and administrator-controlled results.
- Tenant-scoped PDF, DOCX, legacy DOC (Word 97-2003), TXT, and Markdown intake with content validation, SHA-256
  version records, private MinIO storage, Celery job tracking, approval, archive, reindex,
  status, version listing, and authenticated streaming download.
- Immutable document-version uploads with independent file metadata, approval-gated active
  version switching, retrying Celery jobs, and coordinated PostgreSQL/MinIO/Qdrant deletion.
- Structured PDF/DOCX/TXT/Markdown extraction, LangChain recursive chunking, multilingual
  dense embeddings, BM25 sparse embeddings, named Qdrant vectors and payload indexes.
- Tenant-filtered approved/active hybrid search using Qdrant RRF fusion.
- Advanced RAG retrieval with query normalization, kk/ru/en language detection,
  Kazakh-to-Russian dual-query expansion, configurable multilingual reranking,
  prompt-injection filtering, bounded deduplicated context, and deterministic source IDs
  for citation validation.
- Grounded OpenAI Responses generation with citation validation and persisted conversations.
- Follow-up questions in a conversation ("а если на высоте?") are rewritten into standalone
  retrieval queries using recent history; the history is shown to the model for reference
  only and is never a citable source.
- Small-talk shortcuts (greetings, "who are you", weather) answer only when the message is
  nothing but small talk, so safety questions such as "Как ты думаешь, нужна ли каска?" always
  reach retrieval.
- A voice-agent pipeline that transcribes uploaded audio, runs the same tenant-safe RAG chat,
  synthesizes a WAV response, stores audio privately, and exposes authenticated playback.

Audit APIs, the `ai`, `assistant` (WebSocket) and `avatar` modules remain future phases
described in [architecture](docs/architecture.md); their directories are placeholders.

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

For a local organization with one user per role, run the idempotent interactive seed:

```bash
make seed-users
```

It creates `Semyzbay Demo` plus `superadmin@danaai.kz`,
`orgadmin@danaai.kz`, and `user@danaai.kz`. Passwords are entered without echo.
Repeated runs preserve existing passwords; pass `--reset-passwords` directly to
`scripts/seed_users.py` when an intentional reset is required. CI can provide passwords via
`SEED_SUPER_ADMIN_PASSWORD`, `SEED_ORG_ADMIN_PASSWORD`, and `SEED_USER_PASSWORD`.

After migrations, seed the three safety-training demo employees:

```bash
docker compose exec semyzbay-api python scripts/seed_safety_demo.py
```

Enter one development password for all three users, or set
`SEED_SAFETY_EMPLOYEE_PASSWORD` for non-interactive execution. The seed creates Багжан
Толепберген (electrician, height work blocked), Абай Кождан (welder, all assigned work
allowed), and Нуртас Бакбергенов (driver, all work blocked). Every employee has five safety
stages. Repeated runs preserve progress; use `--reset` only to restore the demo statuses.
Use `--reset-passwords` to apply the configured common demo password to all three existing
employee accounts without changing their safety progress.

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
- `POST /voice/ask` (multipart audio question to grounded text and voice response)
- `GET /voice/messages/{message_id}/audio` (authenticated audio playback; add
  `?metadata=true` for the exact spoken text as JSON)
- `POST /speech/transcribe` (standalone authenticated speech-to-text)
- `POST /speech/synthesize` (standalone authenticated MP3/WAV response)
- `GET /speech/voices` (configured ElevenLabs voice and OpenAI fallback voices)
- `GET /safety/employees/me` (current employee safety progress and work clearances)
- `GET /safety/employees`, `GET /safety/employees/{user_id}` (administrator or self)
- `PATCH /safety/employees/{user_id}/stages/{stage_code}` (administrator updates results)
- `POST /conversations`, `GET /conversations`
- `GET /conversations/{conversation_id}/messages`

The defaults use OpenAI `text-embedding-3-large` dense embeddings at 1024 dimensions, local
BM25 sparse embeddings, and `RERANKER_PROVIDER=embedding`, which semantically reranks
multilingual results through the configured embedding provider without loading another
model on the server. Lexical overlap is weak for inflected Kazakh and Russian, so `lexical`
is now only an automatic fallback when the embedding provider fails (or an explicit choice
for offline development). Set `RERANKER_PROVIDER=fastembed` to enable the
Apache-2.0 multilingual `BAAI/bge-reranker-v2-m3-int8` cross-encoder. Its model artifact is
about 570 MB, so production should pre-bake or persist the FastEmbed cache. The first use of
each configured model downloads its artifacts.

Docker Compose mounts the shared `fastembed_cache` named volume at
`/app/.cache/fastembed` for both API and worker. Downloaded sparse/reranker model artifacts
therefore survive container recreation and are reused by document indexing and retrieval.

`POST /rag/retrieve` never accepts unapproved or inactive Qdrant points and uses the same
tenant authorization as knowledge-base search. Retrieved text that resembles an instruction
override is excluded by default. Generation code must treat the returned `context` as
untrusted quoted data and validate final-answer citations with the RAG citation validator.

Grounded chat calls the OpenAI Responses API with `store=false`, refuses generation when
approved context is insufficient, validates every `[S#]` citation before returning an answer,
and persists accepted sources alongside the assistant message. The SSE endpoint emits `status`
events (`rewriting`, `retrieving`, `generating`, `validating`) while it works, but streams the
answer text only after validation completes, so ungrounded model output never reaches
clients. Failures after the stream has started arrive as an `error` event.

Legacy `.doc` uploads are validated by their OLE2 signature in the API and converted to DOCX
by headless LibreOffice in the worker (installed in `docker/Dockerfile.worker`), each
conversion with its own temporary profile and a timeout. The original file is kept for
download.

`POST /voice/ask` accepts FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, or WEBM up to 25 MB.
When configured, it uses ElevenLabs `scribe_v2` for recorded speech and
`eleven_v4_turbo` for Kazakh/Russian voice output. OpenAI `gpt-transcribe` and
`gpt-realtime-2.1-mini` remain automatic fallbacks when ElevenLabs credentials are absent or
the primary provider fails. The JSON response identifies the actual provider, model, format,
transcript, grounded answer, exact `spoken_text`, sources, and authenticated audio URL. Clients
must disclose that
the played voice is AI-generated; downloads return `X-AI-Generated-Voice: true`.

The standalone speech endpoints use the same provider fallback policy. `POST
/speech/transcribe` accepts multipart fields `file` and optional `language` (`kk`, `ru`, or
`en`). `POST /speech/synthesize` accepts JSON with `text` plus optional `language`, `voice_id`,
`speed`, and `output_format`. The audio response headers expose the provider, model, and actual
voice used. All three endpoints require a bearer access token.

The former public MinIO Community container registry stopped allowing anonymous pulls in
2026. For reproducible local development, Compose builds the last pinned AGPL Community
release from its official source tag. This archived release receives no security updates;
production must use a supported MinIO AIStor deployment or a reviewed S3-compatible service.

## Training videos

Approved training clips (`app/modules/videos`) are attached to grounded answers in the
`videos` field of `/chat/messages`, `/voice/ask` and the SSE `completed` event. A video is
never a source of facts: it is suggested only when the answer is `answered`, cites an
instruction the video is linked to, and the question is close enough to the video card
(cosine similarity of the query embedding to the card text and each example question,
`VIDEO_MATCH_MIN_SCORE`, default 0.55). Card vectors are stored in PostgreSQL; a tenant
has at most hundreds of videos, so matching needs no extra Qdrant collection and costs one
query embedding only when a candidate exists.

Uploads go to the `MINIO_VIDEOS_BUCKET`; the worker (ffmpeg is installed in
`docker/Dockerfile.worker`) probes duration and frame size, remuxes MP4/MOV with
`+faststart`, extracts a thumbnail and embeds the card. Playback supports HTTP Range and
short-lived signed links (`VIDEO_URL_TTL_MINUTES`), so `<video src>` works without an
`Authorization` header. The bundled nginx allows 600 MB bodies on `/api/v1/videos`; a
production reverse proxy in front of the API needs the same.

The five work-at-height clips and their cards are seeded with:

```bash
SEED_EMAIL=orgadmin@danaai.kz python scripts/seed_safety_videos.py --videos-dir TB/videos
```

Clips 1-4 are approved. Clip 5 (transfer with two lanyards) stays in review because the
approved instructions do not describe that procedure yet; approve it once a safety
specialist has signed it off. Tune `VIDEO_MATCH_MIN_SCORE` on real questions: too high
hides relevant clips, too low shows clips next to loosely related answers.

## Upgrading Qdrant 1.15 → 1.20 and reindexing

Compose now runs `qdrant/qdrant:v1.20.0`, matching `qdrant-client` 1.20. Qdrant 1.20 cannot
open storage written by 1.15 (it panics with ``unknown variant `rocks_db` ``), so the service
uses a new empty volume, `qdrant_data_v1_20`; the old `qdrant_data` volume is left untouched
for rollback. Vectors are derived data and are rebuilt from PostgreSQL and the original
files in MinIO:

```bash
docker compose up -d --build
REINDEX_EMAIL=orgadmin@danaai.kz python scripts/reindex_documents.py
```

Run the reindex once per organization (a `super_admin` passes `--organization-id`). Approval
status and active versions are preserved; each document becomes searchable again as soon as
its job succeeds. After verifying search, the old volume can be removed with
`docker volume rm semyzbay_qdrant_data`.

The same reindex is required after the chunking change below, so one run covers both.

Chunking merges consecutive paragraphs of the same section and page before splitting, so
chunks fill up to `DOCUMENT_CHUNK_SIZE` (1200 characters) instead of one chunk per paragraph.
DOCX/DOC sections are detected from Word heading styles and from numbered top-level headings
such as "1. Общие требования безопасности" or "2.Требования безопасности перед началом
работы" (numbers must run in sequence, so restarted numbered lists are not mistaken for
headings). On the 27 instructions from `TB/` this produced 464 chunks with a median of
~1070 characters instead of ~2970 chunks of ~105 characters, and 82% of chunks now carry a
section title.

## Retrieval evaluation

`evaluation/datasets/tb_starter.jsonl` holds a starter set of Russian and Kazakh questions
mapped to instruction numbers from `TB/`. With the stack running and documents uploaded
(titles must contain the instruction number, e.g. "Инструкция №90 - по ТБ при работе на
высоте") and approved:

```bash
EVAL_EMAIL=orgadmin@danaai.kz make eval EVAL_ARGS="--min-hit-rate 0.8 --output tmp/eval.json"
```

The script uses only `POST /rag/retrieve`, so it spends embedding but not generation tokens.
It prints hit@1, hit@k, MRR, the insufficient-context rate and latency, and exits non-zero
below `--min-hit-rate`. Run it before and after changing chunking, reranking, or relevance
thresholds. The starter set was derived from instruction titles; have a safety specialist
review it and extend it with real employee questions.

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
