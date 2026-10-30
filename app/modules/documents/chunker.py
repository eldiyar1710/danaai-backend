from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.modules.documents.parser import ParsedBlock


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    page_number: int | None
    section_title: str | None
    section_number: str | None


def chunk_blocks(
    blocks: list[ParsedBlock], *, chunk_size: int, chunk_overlap: int
) -> list[TextChunk]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    chunks: list[TextChunk] = []
    for block in blocks:
        for text in splitter.split_text(block.text):
            clean = text.strip()
            if clean:
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        text=clean,
                        page_number=block.page_number,
                        section_title=block.section_title,
                        section_number=block.section_number,
                    )
                )
    if not chunks:
        raise ValueError("Document chunking produced no content")
    return chunks
