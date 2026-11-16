from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.robot.knowledge import cached_knowledge
from app.modules.robot.router import router


def create_robot_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="University robot",
        version="0.1.0",
        description="The robot sends a question and receives a spoken answer using an API key.",
    )
    application.include_router(router, prefix=settings.api_v1_prefix)

    @application.get("/health")
    def health() -> dict[str, int | str]:
        knowledge = cached_knowledge(
            settings.knowledge_dir,
            settings.document_chunk_size,
            settings.document_chunk_overlap,
        )
        approved = {
            name.strip() for name in settings.robot_approved_pdfs.split(",") if name.strip()
        }
        approved -= {"5.pdf", "Каталог знаний.pdf"}
        return {
            "status": "ok",
            "approved_passages": sum(p.file_name in approved for p in knowledge.passages),
        }

    return application


app = create_robot_app()
