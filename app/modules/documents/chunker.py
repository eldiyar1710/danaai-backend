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


def _merge_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """Join consecutive blocks that share a page and section.

    DOCX/DOC parsing yields one block per paragraph, often a single list item such as
    "- обучение безопасным методам;". Splitting each paragraph on its own produced chunks of
    ~100 characters without context. Merged text is split by the recursive splitter below, so
    chunks fill up to ``chunk_size`` and never cross a page or section boundary.
    """
    merged: list[ParsedBlock] = []
    buffer: list[str] = []
    current: ParsedBlock | None = None

    def flush() -> None:
        if current is not None and buffer:
            merged.append(
                ParsedBlock(
                    text="\n".join(buffer),
                    page_number=current.page_number,
                    section_title=current.section_title,
                    section_number=current.section_number,
                )
            )

    for block in blocks:
        key = (block.page_number, block.section_title, block.section_number)
        if current is None or key != (
            current.page_number,
            current.section_title,
            current.section_number,
        ):
            flush()
            buffer = []
            current = block
        buffer.append(block.text)
    flush()
    return merged


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
    for block in _merge_blocks(blocks):
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
