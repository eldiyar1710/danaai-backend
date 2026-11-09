from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.database import create_engine, create_session_factory
from app.core.exceptions import register_exception_handlers
from app.core.health import check_dependencies
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.integrations.minio_client import create_minio_client
from app.integrations.qdrant_client import create_qdrant_client
from app.integrations.redis_client import create_redis_client
from app.modules.auth.router import router as auth_router
from app.modules.conversations.router import router as conversations_router
from app.modules.documents.router import router as documents_router
from app.modules.knowledge_base.router import router as knowledge_base_router
from app.modules.organizations.router import router as organizations_router
from app.modules.rag.router import router as rag_router
from app.modules.safety.router import router as safety_router
from app.modules.speech.router import router as speech_router
from app.modules.users.router import router as users_router
from app.modules.voice.router import router as voice_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        app.state.db_engine = create_engine(app_settings)
        app.state.session_factory = create_session_factory(app.state.db_engine)
        app.state.redis = create_redis_client(app_settings)
        app.state.qdrant = create_qdrant_client(app_settings)
        app.state.minio = create_minio_client(app_settings)
        yield
        await app.state.redis.aclose()
        await app.state.qdrant.close()
        await app.state.db_engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="Tenant-isolated safety knowledge platform API",
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)
    application.include_router(auth_router, prefix=app_settings.api_v1_prefix)
    application.include_router(conversations_router, prefix=app_settings.api_v1_prefix)
    application.include_router(documents_router, prefix=app_settings.api_v1_prefix)
    application.include_router(knowledge_base_router, prefix=app_settings.api_v1_prefix)
    application.include_router(organizations_router, prefix=app_settings.api_v1_prefix)
    application.include_router(rag_router, prefix=app_settings.api_v1_prefix)
    application.include_router(safety_router, prefix=app_settings.api_v1_prefix)
    application.include_router(speech_router, prefix=app_settings.api_v1_prefix)
    application.include_router(users_router, prefix=app_settings.api_v1_prefix)
    application.include_router(voice_router, prefix=app_settings.api_v1_prefix)

    @application.get("/health", tags=["health"], summary="Process liveness")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": app_settings.app_name}

    @application.get("/health/ready", tags=["health"], summary="Dependency readiness")
    async def readiness(request: Request) -> JSONResponse:
        dependencies = await check_dependencies(
            engine=request.app.state.db_engine,
            redis=request.app.state.redis,
            qdrant=request.app.state.qdrant,
            minio=request.app.state.minio,
            timeout_seconds=app_settings.healthcheck_timeout_seconds,
        )
        is_ready = all(value["status"] == "up" for value in dependencies.values())
        payload: dict[str, Any] = {
            "status": "ready" if is_ready else "not_ready",
            "dependencies": dependencies,
        }
        return JSONResponse(
            status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    return application


app = create_app()
