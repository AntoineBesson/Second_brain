from datetime import datetime, timezone

from backend.ingestion.fetch import fetch_bytes
from backend.memory.vector import _chunk, store_chunk

try:
    import fitz
except ImportError:
    fitz = None  # type: ignore


async def ingest_pdf(
    source,
    filename: str = "document.pdf",
    auth: tuple[str, str] | None = None,
) -> int:
    """Extract text from a PDF and store chunks in Qdrant.

    source: UploadFile, local path str/Path, or HTTP URL str.
    Returns number of chunks stored.
    """
    if fitz is None:
        raise ImportError("pymupdf required: pip install pymupdf")

    raw = await fetch_bytes(source, auth=auth)
    with fitz.open(stream=raw, filetype="pdf") as doc:
        pages = [page.get_text("text") for page in doc]

    full_text = "\n\n".join(pages)
    chunks = _chunk(full_text)
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        store_chunk(chunk, {
            "source_type": "pdf",
            "source_url": "",
            "title": filename,
            "date_added": now,
            "chunk_index": i,
            "tags": [],
        })

    return len(chunks)
