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
