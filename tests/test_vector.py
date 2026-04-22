import httpx
import pytest
from unittest.mock import MagicMock, patch

from backend.memory.vector import EmbedResult, embed, _chunk


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


def test_chunk_returns_single_chunk_for_short_text():
    result = _chunk("hello world foo bar")
    assert result == ["hello world foo bar"]


def test_chunk_splits_with_overlap():
    # 100 words, size=60, overlap=10
    # chunk 0: words[0:60]  (60 words)
    # chunk 1: words[50:100] (50 words — last chunk is shorter)
    words = ["w"] * 100
    text = " ".join(words)
    chunks = _chunk(text, size=60, overlap=10)
    assert len(chunks) == 2
    assert len(chunks[0].split()) == 60
    assert len(chunks[1].split()) == 50


def test_chunk_raises_on_invalid_overlap():
    with pytest.raises(ValueError, match="overlap"):
        _chunk("hello world", size=10, overlap=10)


import uuid as uuid_mod
from backend.memory.vector import store_chunk


def test_store_chunk_embeds_and_upserts():
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")
    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.upsert = MagicMock()

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant_client", mock_qdrant):
        result = store_chunk("some text", {"source_type": "whatsapp", "chunk_index": 0})

    # Returns a valid UUID string
    uuid_mod.UUID(result)

    mock_qdrant.upsert.assert_called_once()
    call_kwargs = mock_qdrant.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "brain"
    point = call_kwargs["points"][0]
    assert point.payload["text"] == "some text"
    assert point.vector == [0.1] * 768


from backend.memory.vector import search


def test_search_returns_payload_list():
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")

    mock_hit = MagicMock()
    mock_hit.payload = {"text": "relevant chunk", "source_type": "whatsapp"}

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.search = MagicMock(return_value=[mock_hit])

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant_client", mock_qdrant):
        results = search("my query")

    assert len(results) == 1
    assert results[0]["text"] == "relevant chunk"
    mock_qdrant.search.assert_called_once_with(
        collection_name="brain",
        query_vector=[0.1] * 768,
        limit=5,
        query_filter=None,
    )


def test_search_returns_empty_when_collection_missing():
    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=False)

    with patch("backend.memory.vector._qdrant_client", mock_qdrant):
        results = search("my query")

    assert results == []
    mock_qdrant.search.assert_not_called()


def test_search_correct_chunk_in_top_3():
    """Store 3 distinct payloads; mock Qdrant to return them ranked by relevance score."""
    chunks = [
        {"text": "Python is a high-level programming language", "score": 0.9},
        {"text": "Cats sleep for 16 hours a day", "score": 0.3},
        {"text": "The Eiffel Tower is in Paris", "score": 0.2},
    ]
    mock_embed_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")

    mock_hits = []
    for c in sorted(chunks, key=lambda x: x["score"], reverse=True):
        hit = MagicMock()
        hit.payload = {"text": c["text"]}
        hit.score = c["score"]
        mock_hits.append(hit)

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists = MagicMock(return_value=True)
    mock_qdrant.search = MagicMock(return_value=mock_hits)

    with patch("backend.memory.vector.embed", return_value=mock_embed_result), \
         patch("backend.memory.vector._qdrant_client", mock_qdrant):
        results = search("What programming language should I learn?", top_k=3)

    texts = [r["text"] for r in results]
    assert "Python is a high-level programming language" in texts
    assert texts.index("Python is a high-level programming language") == 0
