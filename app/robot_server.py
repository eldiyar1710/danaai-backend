from fastapi import FastAPI, HTTPException

from app.core.config import get_settings
from app.modules.robot.knowledge import cached_knowledge, resolve_project_path
from app.modules.robot.router import router
from app.modules.robot.semantic import fingerprint, load_index


def create_robot_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="University robot",
        version="0.1.0",
        description="The robot sends a question and receives a spoken answer using an API key.",
    )
    application.include_router(router, prefix=settings.api_v1_prefix)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/ready")
    def ready() -> dict[str, int | str]:
        if not settings.robot_api_key or not settings.robot_api_key.get_secret_value().strip():
            raise HTTPException(status_code=503, detail="Robot API key is not configured")
        if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
            raise HTTPException(status_code=503, detail="OpenAI provider is not configured")
        try:
            knowledge = cached_knowledge(
                settings.knowledge_dir,
                settings.robot_approval_manifest,
                settings.document_chunk_size,
                settings.document_chunk_overlap,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Robot approvals are invalid") from exc
        if not knowledge.passages:
            raise HTTPException(status_code=503, detail="No approved university pages")
        index = load_index(
            str(resolve_project_path(settings.robot_index_path)),
            fingerprint(knowledge.passages),
            settings.embedding_model,
            settings.embedding_dimension,
            len(knowledge.passages),
        )
        if index is None:
            raise HTTPException(status_code=503, detail="Semantic index is not ready")
        return {"status": "ready", "approved_passages": len(knowledge.passages)}

    return application


app = create_robot_app()
