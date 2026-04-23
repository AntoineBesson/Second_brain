import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from backend.ingestion.pdf import ingest_pdf
from backend.ingestion.registry import registry
from backend.ingestion.url import ingest_url
from backend.ingestion.youtube import ingest_youtube
from backend.scheduler.reminders import _send_whatsapp

logger = logging.getLogger(__name__)
router = APIRouter()


async def run_ingest(
    task_id: str,
    source_type: str,
    source: str,
    chat_id: str,
    auth: tuple[str, str] | None = None,
) -> None:
    """Background task: run ingestion and notify the user via WhatsApp when done."""
    try:
        if source_type == "pdf":
            raw = source.split("/")[-1].split("?")[0]
            if not raw:
                logger.warning("Could not extract filename from URL %r; using 'document.pdf'", source)
            filename = raw or "document.pdf"
            n = await ingest_pdf(source, filename=filename, auth=auth)
            label = "PDF"
        elif source_type == "url":
            n = await ingest_url(source)
            label = "URL"
        elif source_type == "youtube":
            n = await ingest_youtube(source)
            label = "video"
        else:
            raise ValueError(f"Unknown source type: {source_type}")

        registry.update(task_id, status="complete", chunks_stored=n)
        await _send_whatsapp(f"Done — ingested {n} chunks from your {label}.", chat_id)
    except Exception as exc:
        logger.error("Ingestion failed for task %s: %s", task_id, exc)
        registry.update(task_id, status="error", error_msg=str(exc))
        await _send_whatsapp(f"Sorry, ingestion failed: {exc}", chat_id)


@router.post("/ingest")
async def ingest(request: Request) -> dict:
    """Synchronous ingestion endpoint. Accepts JSON or multipart/form-data.

    JSON body: {"type": "pdf"|"url"|"youtube", "url": "...", "path": "..."}
    Form data: type=pdf, file=<UploadFile>, url=..., path=...
    Returns: {"chunks_stored": N, "source": "..."}
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        ingest_type = form.get("type")
        url = form.get("url")
        path = form.get("path")
        upload = form.get("file")
    else:
        body = await request.json()
        ingest_type = body.get("type")
        url = body.get("url")
        path = body.get("path")
        upload = None

    try:
        if ingest_type == "pdf":
            source = upload or url or path
            if not source:
                raise HTTPException(status_code=422, detail="PDF requires file, url, or path")
            if upload:
                filename = getattr(upload, "filename", None) or "document.pdf"
            elif url:
                raw = url.split("/")[-1].split("?")[0]
                if not raw:
                    logger.warning("Could not extract filename from URL %r; using 'document.pdf'", url)
                filename = raw or "document.pdf"
            else:
                filename = Path(path).name if path else "document.pdf"
            n = await ingest_pdf(source, filename=filename)
            return {"chunks_stored": n, "source": filename}

        elif ingest_type == "url":
            if not url:
                raise HTTPException(status_code=422, detail="URL ingestion requires 'url'")
            n = await ingest_url(url)
            return {"chunks_stored": n, "source": url}

        elif ingest_type == "youtube":
            if not url:
                raise HTTPException(status_code=422, detail="YouTube ingestion requires 'url'")
            n = await ingest_youtube(url)
            return {"chunks_stored": n, "source": url}

        else:
            raise HTTPException(status_code=422, detail=f"Unknown ingestion type: {ingest_type!r}")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ingest/{task_id}/status")
async def ingest_status(task_id: str) -> dict:
    status = registry.get(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "status": status.status,
        "chunks_stored": status.chunks_stored,
        "error_msg": status.error_msg,
    }
