# Semyzbay backend architecture

## Target structure

The codebase is a modular monolith. `app/core` owns cross-cutting runtime concerns;
`app/integrations` owns protocol clients; each directory in `app/modules` owns a business
capability and will contain its router, schemas, repository, service, and domain-specific
adapters. Celery runs the same application modules out-of-process for expensive work.

```text
app/
├── main.py
├── core/                 configuration, DB, logging, middleware, health
├── integrations/         Redis, Qdrant, MinIO clients
├── modules/
│   ├── auth/             sessions, JWT, RBAC
│   ├── organizations/    tenant lifecycle
│   ├── users/            tenant users
│   ├── documents/        versions, parsing, approval, processing
│   ├── knowledge_base/   tenant-filtered search API
│   ├── rag/              retrieval, reranking, context, validation
│   ├── ai/               (planned) replaceable provider interfaces
│   ├── speech/           STT and TTS
│   ├── voice/            voice question → grounded chat → synthesized answer
│   ├── assistant/        (planned) WebSocket orchestration
│   ├── conversations/    messages, history-aware follow-ups, citations
│   ├── safety/           training stages, work scopes, clearances
│   ├── videos/           approved training clips suggested next to grounded answers
│   ├── settings/         (model only) global/tenant AI configuration
│   ├── avatar/           (planned) playback metadata only
│   └── audit/            (model only) immutable security audit events
└── workers/              Celery application and tasks
```

Routers perform HTTP adaptation and authorization only. Services own use cases,
repositories own persistence, and external providers are injected behind explicit
interfaces. Tenant identity comes from the authenticated principal, never directly from a
client-controlled organization field.

## PostgreSQL model

The initial migration creates all requested core tables: `organizations`, `users`,
`refresh_sessions`, `documents`, `document_versions`, `document_chunks`, `conversations`,
`messages`, `message_sources`, `ai_settings`, `processing_jobs`, and `audit_logs`.

All primary keys are UUIDs and all timestamps are timezone-aware UTC. Compound tenant
indexes support normal access patterns. Composite foreign keys bind chunks to a document
and its exact version, preventing cross-document references. The active version foreign key
binds a document only to one of its own versions. Super-admin organization nullability is
enforced with a check constraint.

## Qdrant architecture

One collection, `semyzbay_documents`, will use named vectors:

- `dense`: cosine distance; OpenAI `text-embedding-3-large` at 1024 dimensions by default
  (`EMBEDDING_PROVIDER=fastembed` switches to a local FastEmbed model such as BGE-M3).
- `sparse`: BM25-compatible sparse vectors; indices and values are stored independently
  from the dense representation.

Chunks are built per section and page: consecutive paragraphs are merged and then split
recursively up to the configured chunk size, so a chunk never crosses a section boundary.
Numbered top-level headings ("1. Общие требования …") become section titles when Word
heading styles are absent. Server and client are both Qdrant 1.20; any change to parsing,
chunking or embeddings requires `scripts/reindex_documents.py`.

Every point payload contains `organization_id`, `document_id`, `document_version_id`,
`chunk_id`, `approval_status`, `is_active`, `language`, `equipment_type`, page/section, and
text. Keyword payload indexes cover the tenant and lifecycle fields. Retrieval adapters
construct the mandatory organization + approved + active filter internally before issuing
dense or sparse prefetch queries. Results are fused with RRF and only then reranked
(embedding cosine reranking by default, lexical fallback, optional FastEmbed cross-encoder).
Changing embedding configuration creates a versioned collection/alias and requires a
controlled reindex before alias promotion.

## Dependency strategy

Runtime and development direct dependencies are exactly pinned in `requirements.lock` and
`requirements-dev.lock`. The infrastructure phase intentionally excludes heavyweight AI
packages; they are added and compatibility-locked in Phase 4 when their provider adapters
and model tests exist. This keeps the API/worker image deterministic and small during the
infrastructure and authentication phases.

## Delivery sequence and gates

1. Infrastructure: Compose topology, settings, async clients, migrations, health/readiness,
   lint and unit tests.
2. Authentication: Argon2, access/rotating refresh tokens, RBAC, tenant-aware repositories.
3. Documents: validated upload, private MinIO storage, versions, approval, idempotent jobs.
4. LangChain/indexing: structured parsers/chunking, BGE-M3, BM25 sparse vectors, Qdrant.
5. Advanced RAG: filtered hybrid retrieval, RRF, multilingual reranker, bounded context,
   grounded structured generation and deterministic citation validation.
6. Chat/evaluation, then speech, WebSocket/avatar metadata, and hardening.

Each phase must pass unit tests plus its integration gate before the next is declared ready.

Phases 1 to 5 are implemented: validated storage (including legacy DOC conversion),
structured parsing, LangChain chunking, dense and BM25 sparse indexing, approval-gated
Qdrant activation, tenant-filtered RRF search, multilingual reranking, grounded generation
with citation validation, and history-aware follow-up questions. Phase 6 is partly done:
chat, SSE with progress events, speech, the voice agent, and safety training are in place;
the retrieval evaluation harness lives in `scripts/evaluate_rag.py` with datasets under
`evaluation/datasets`. WebSocket/avatar metadata, audit APIs, and hardening remain.
