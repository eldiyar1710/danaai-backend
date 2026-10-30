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
│   ├── ai/               replaceable provider interfaces
│   ├── speech/           STT and TTS
│   ├── assistant/        text/voice orchestration and WebSocket
│   ├── conversations/    messages and citations
│   ├── settings/         global/tenant AI configuration
│   ├── avatar/           playback metadata only
│   └── audit/            immutable security audit events
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

- `dense`: BGE-M3 output, cosine distance; its dimension is discovered from the model.
- `sparse`: BM25-compatible sparse vectors; indices and values are stored independently
  from the dense representation.

Every point payload contains `organization_id`, `document_id`, `document_version_id`,
`chunk_id`, `approval_status`, `is_active`, `language`, `equipment_type`, page/section, and
text. Keyword payload indexes cover the tenant and lifecycle fields. Retrieval adapters
construct the mandatory organization + approved + active filter internally before issuing
dense or sparse prefetch queries. Results are fused with RRF and only then reranked.
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

Phases 1 and 2 have passed their local integration gates. The document pipeline now includes
validated storage, structured parsing, LangChain chunking, dense and BM25 sparse indexing,
approval-gated Qdrant activation, and tenant-filtered RRF search. The lightweight local
FastEmbed model is configurable; production BGE-M3 deployment and multilingual reranking
remain part of the next quality gate.
