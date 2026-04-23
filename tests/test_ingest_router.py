import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.router.ingest import router

app_test = FastAPI()
app_test.include_router(router)


async def test_post_ingest_json_url():
    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=12)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "url", "url": "https://example.com"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 12
    assert body["source"] == "https://example.com"


async def test_post_ingest_json_youtube():
    with patch("backend.router.ingest.ingest_youtube", AsyncMock(return_value=7)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 7
    assert body["source"] == "https://youtu.be/dQw4w9WgXcQ"


async def test_post_ingest_json_pdf_url():
    with patch("backend.router.ingest.ingest_pdf", AsyncMock(return_value=5)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "pdf", "url": "https://example.com/doc.pdf"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_stored"] == 5
    assert body["source"] == "doc.pdf"


async def test_post_ingest_multipart_url():
    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=8)):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                data={"type": "url", "url": "https://example.com/article"},
            )
    assert resp.status_code == 200
    assert resp.json()["chunks_stored"] == 8


async def test_post_ingest_returns_500_on_ingestion_failure():
    with patch("backend.router.ingest.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))):
        async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
            resp = await ac.post(
                "/ingest",
                json={"type": "url", "url": "https://example.com"},
            )
    assert resp.status_code == 500


async def test_post_ingest_returns_422_on_unknown_type():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.post(
            "/ingest",
            json={"type": "docx", "url": "https://example.com"},
        )
    assert resp.status_code == 422


async def test_post_ingest_returns_422_when_url_missing_for_url_type():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.post(
            "/ingest",
            json={"type": "url"},
        )
    assert resp.status_code == 422


# --- run_ingest background task ---

async def test_run_ingest_updates_registry_to_complete_on_success():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    with patch("backend.router.ingest.ingest_url", AsyncMock(return_value=9)), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()) as mock_send:
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "url", "https://example.com", "+33612345678")

    status = registry.get(task_id)
    assert status.status == "complete"
    assert status.chunks_stored == 9
    mock_send.assert_awaited_once()
    assert "9" in str(mock_send.call_args)


async def test_run_ingest_updates_registry_to_error_on_failure():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    with patch("backend.router.ingest.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()) as mock_send:
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "url", "https://example.com", "+33612345678")

    status = registry.get(task_id)
    assert status.status == "error"
    assert "insufficient content" in status.error_msg
    mock_send.assert_awaited_once()
    assert "failed" in str(mock_send.call_args).lower()


async def test_run_ingest_pdf_passes_auth_to_ingester():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    mock_ingest_pdf = AsyncMock(return_value=3)
    with patch("backend.router.ingest.ingest_pdf", mock_ingest_pdf), \
         patch("backend.router.ingest._send_whatsapp", AsyncMock()):
        from backend.router.ingest import run_ingest
        await run_ingest(task_id, "pdf", "https://api.twilio.com/media.pdf", "+33612345678",
                         auth=("ACXXX", "token"))

    assert mock_ingest_pdf.call_args.kwargs["auth"] == ("ACXXX", "token")


# --- Status endpoint ---

async def test_get_ingest_status_pending():
    from backend.ingestion.registry import registry
    task_id = registry.create()

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["chunks_stored"] is None
    assert body["error_msg"] is None


async def test_get_ingest_status_complete():
    from backend.ingestion.registry import registry
    task_id = registry.create()
    registry.update(task_id, status="complete", chunks_stored=42)

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "complete"
    assert body["chunks_stored"] == 42


async def test_get_ingest_status_error():
    from backend.ingestion.registry import registry
    task_id = registry.create()
    registry.update(task_id, status="error", error_msg="embedding failed")

    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get(f"/ingest/{task_id}/status")

    body = resp.json()
    assert body["status"] == "error"
    assert body["error_msg"] == "embedding failed"


async def test_get_ingest_status_unknown_id_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app_test), base_url="http://test") as ac:
        resp = await ac.get("/ingest/00000000-0000-0000-0000-000000000000/status")
    assert resp.status_code == 404
