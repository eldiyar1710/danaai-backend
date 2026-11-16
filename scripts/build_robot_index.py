"""Build the semantic search index after PDF pages have been reviewed."""

import asyncio

from app.core.config import get_settings
from app.modules.robot.knowledge import cached_knowledge, resolve_project_path
from app.modules.robot.semantic import build_index


async def main() -> None:
    settings = get_settings()
    knowledge = cached_knowledge(
        settings.knowledge_dir,
        settings.robot_approval_manifest,
        settings.document_chunk_size,
        settings.document_chunk_overlap,
    )
    count = await build_index(
        settings, knowledge, resolve_project_path(settings.robot_index_path)
    )
    print(f"Indexed {count} approved university passages")


if __name__ == "__main__":
    asyncio.run(main())
