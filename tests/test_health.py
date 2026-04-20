# tests/test_health.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- check_postgres ---

async def test_check_postgres_ok():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.AsyncSessionLocal", return_value=mock_cm):
        from backend.health import check_postgres
        result = await check_postgres()

    assert result == "ok"


async def test_check_postgres_error():
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.AsyncSessionLocal", return_value=mock_cm):
        from backend.health import check_postgres
        result = await check_postgres()

    assert result.startswith("error:")


# --- check_qdrant ---

async def test_check_qdrant_ok():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_qdrant
        result = await check_qdrant()

    assert result == "ok"


async def test_check_qdrant_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("refused"))

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_qdrant
        result = await check_qdrant()

    assert result.startswith("error:")


# --- check_ollama ---

async def test_check_ollama_ok():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [
            {"name": "nomic-embed-text:latest"},
            {"name": "gemma3:4b"},
        ]
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result == "ok"


async def test_check_ollama_missing_model():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "models": [{"name": "nomic-embed-text:latest"}]  # gemma3:4b absent
    })

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result.startswith("error:")
    assert "gemma3:4b" in result


async def test_check_ollama_network_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))

    mock_client_cm = MagicMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.health.httpx.AsyncClient", return_value=mock_client_cm):
        from backend.health import check_ollama
        result = await check_ollama()

    assert result.startswith("error:")
