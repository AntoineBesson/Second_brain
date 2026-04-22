import httpx
import pytest
from unittest.mock import MagicMock, patch

from backend.memory.vector import EmbedResult, embed


def test_embed_returns_ollama_vector():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"embedding": [0.1, 0.2, 0.3]})

    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(return_value=mock_response)

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx):
        result = embed("hello world")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.model == "nomic-embed-text"
    assert result.source == "ollama"


def test_embed_falls_back_to_openai_on_ollama_error():
    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(side_effect=httpx.ConnectError("ollama down"))
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mock_data = MagicMock()
    mock_data.embedding = [0.4, 0.5, 0.6]
    mock_openai_resp = MagicMock()
    mock_openai_resp.data = [mock_data]
    mock_openai_client = MagicMock()
    mock_openai_client.embeddings.create = MagicMock(return_value=mock_openai_resp)

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx), \
         patch("backend.memory.vector.OpenAI", return_value=mock_openai_client):
        result = embed("hello world")

    assert result.vector == [0.4, 0.5, 0.6]
    assert result.model == "text-embedding-3-small"
    assert result.source == "openai"


def test_embed_raises_runtime_error_when_both_fail():
    mock_http_client = MagicMock()
    mock_http_client.post = MagicMock(side_effect=httpx.ConnectError("ollama down"))
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_http_client)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mock_openai_client = MagicMock()
    mock_openai_client.embeddings.create = MagicMock(side_effect=Exception("OpenAI down"))

    with patch("backend.memory.vector.httpx.Client", return_value=mock_ctx), \
         patch("backend.memory.vector.OpenAI", return_value=mock_openai_client):
        with pytest.raises(RuntimeError, match="Embedding unavailable"):
            embed("hello world")
