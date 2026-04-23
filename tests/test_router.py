# tests/test_router.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from backend.router.intent import Tier1Response, _call_haiku_fallback, _call_ollama, _parse_response, call_tier1
from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.api import MessageRequest, MessageResponse, message


# ---------------------------------------------------------------------------
# Tier 1 happy path — Ollama returns valid JSON
# ---------------------------------------------------------------------------

async def test_call_tier1_happy_path():
    expected = Tier1Response(
        intent="general",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Hello there!",
    )
    with patch("backend.router.intent._call_ollama", AsyncMock(return_value=expected)):
        result = await call_tier1("Hello")

    assert result.intent == "general"
    assert result.complexity == 0.3
    assert result.escalate is False
    assert result.response == "Hello there!"


# ---------------------------------------------------------------------------
# Tier 1 fallback — Ollama raises, Haiku is called instead
# ---------------------------------------------------------------------------

async def test_call_tier1_falls_back_to_haiku_on_ollama_error():
    haiku_result = Tier1Response(
        intent="general",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="Hi from Haiku",
    )
    with patch(
        "backend.router.intent._call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("ollama down")),
    ), patch(
        "backend.router.intent._call_haiku_fallback",
        AsyncMock(return_value=haiku_result),
    ):
        result = await call_tier1("Hello")

    assert result.response == "Hi from Haiku"


# ---------------------------------------------------------------------------
# _call_ollama parses the Ollama /api/chat JSON envelope correctly
# ---------------------------------------------------------------------------

async def test_call_ollama_parses_response():
    payload = {
        "intent": "recall",
        "complexity": 0.4,
        "escalate": False,
        "escalation_reason": "",
        "response": "Here is what I found.",
    }
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={"message": {"content": json.dumps(payload)}}
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.router.intent.httpx.AsyncClient", return_value=mock_cm):
        result = await _call_ollama("What did I save yesterday?")

    assert result.intent == "recall"
    assert result.complexity == 0.4
    assert result.response == "Here is what I found."


# ---------------------------------------------------------------------------
# _call_haiku_fallback parses the Anthropic response correctly
# ---------------------------------------------------------------------------

async def test_call_haiku_fallback_parses_response():
    payload = {
        "intent": "general",
        "complexity": 0.1,
        "escalate": False,
        "escalation_reason": "",
        "response": "I can help with that.",
    }
    mock_content = MagicMock()
    mock_content.text = json.dumps(payload)

    mock_msg = MagicMock()
    mock_msg.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("backend.router.intent.AsyncAnthropic", return_value=mock_client):
        result = await _call_haiku_fallback("Hi")

    assert result.intent == "general"
    assert result.response == "I can help with that."


# ---------------------------------------------------------------------------
# _parse_response — error handling
# ---------------------------------------------------------------------------


def test_parse_response_raises_on_bad_json():
    with pytest.raises(ValueError, match="Failed to parse LLM response"):
        _parse_response("not valid json {{")


def test_parse_response_raises_on_missing_key():
    with pytest.raises(ValueError, match="Failed to parse LLM response"):
        _parse_response('{"complexity": 0.5, "escalate": false, "response": "hi"}')  # missing "intent"


def test_parse_response_clamps_complexity():
    result = _parse_response(
        '{"intent": "general", "complexity": 1.8, "escalate": false, '
        '"escalation_reason": "", "response": "ok"}'
    )
    assert result.complexity == 1.0


def test_parse_response_handles_string_escalate_false():
    result = _parse_response(
        '{"intent": "general", "complexity": 0.3, "escalate": "false", '
        '"escalation_reason": "", "response": "ok"}'
    )
    assert result.escalate is False


# ---------------------------------------------------------------------------
# should_escalate — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_should_escalate_on_high_complexity():
    r = Tier1Response(intent="general", complexity=0.8, escalate=False,
                      escalation_reason="", response="")
    assert should_escalate(r) is True


def test_should_escalate_on_escalate_flag():
    r = Tier1Response(intent="query", complexity=0.2, escalate=True,
                      escalation_reason="nuanced question", response="")
    assert should_escalate(r) is True


def test_should_not_escalate_on_low_complexity_no_flag():
    r = Tier1Response(intent="general", complexity=0.3, escalate=False,
                      escalation_reason="", response="Hello!")
    assert should_escalate(r) is False


def test_should_not_escalate_at_exact_threshold():
    r = Tier1Response(intent="general", complexity=0.7, escalate=False,
                      escalation_reason="", response="")
    assert should_escalate(r) is False


def test_should_escalate_on_escalation_intent():
    # "synthesize" is outside the standard intent enum but may be returned by a model
    r = Tier1Response(intent="synthesize", complexity=0.5, escalate=False,
                      escalation_reason="", response="")
    assert should_escalate(r) is True


# ---------------------------------------------------------------------------
# log_escalation — mocks DB session
# ---------------------------------------------------------------------------

async def test_log_escalation_writes_to_db():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.router.escalation.AsyncSessionLocal", return_value=mock_cm):
        await log_escalation("complex question", "complexity=0.80", "chat_001")

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    # Verify the correct bind parameters were passed
    bound_params = mock_session.execute.call_args.args[1]
    assert bound_params["message"] == "complex question"
    assert bound_params["reason"] == "complexity=0.80"
    assert bound_params["chat_id"] == "chat_001"


# ---------------------------------------------------------------------------
# call_tier2 — mocks Anthropic client
# ---------------------------------------------------------------------------

async def test_call_tier2_returns_response():
    tier1 = Tier1Response(
        intent="general", complexity=0.9, escalate=False,
        escalation_reason="", response="partial answer"
    )
    mock_content = MagicMock()
    mock_content.text = "Full detailed answer from Sonnet."

    mock_msg = MagicMock()
    mock_msg.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("backend.router.escalation.AsyncAnthropic", return_value=mock_client):
        result = await call_tier2("What is the meaning of life?", tier1)

    assert result == "Full detailed answer from Sonnet."
    # Verify Tier 1's partial response was included as context
    call_args = mock_client.messages.create.call_args
    user_content = call_args.kwargs["messages"][0]["content"]
    assert "partial answer" in user_content
    assert "What is the meaning of life?" in user_content


# ---------------------------------------------------------------------------
# POST /message — Tier 1 path (no escalation)
# ---------------------------------------------------------------------------

async def test_message_endpoint_uses_tier1_when_no_escalation():
    tier1_result = Tier1Response(
        intent="general",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Hello from Tier 1",
    )
    req = MessageRequest(text="Hello", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)):
        result = await message(req)

    assert result.tier_used == 1
    assert result.response == "Hello from Tier 1"
    assert result.intent == "general"


# ---------------------------------------------------------------------------
# POST /message — Tier 2 path (escalation triggered by high complexity)
# ---------------------------------------------------------------------------

async def test_message_endpoint_escalates_to_tier2():
    tier1_result = Tier1Response(
        intent="general",
        complexity=0.9,
        escalate=False,
        escalation_reason="",
        response="Partial from Tier 1",
    )
    req = MessageRequest(text="Analyze the nature of consciousness", chat_id="chat_002")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.call_tier2", AsyncMock(return_value="Deep Sonnet answer")), \
         patch("backend.router.api.log_escalation", AsyncMock()):
        result = await message(req)

    assert result.tier_used == 2
    assert result.response == "Deep Sonnet answer"
    assert result.intent == "general"


# ---------------------------------------------------------------------------
# POST /message — Error handling (Tier 1 failure)
# ---------------------------------------------------------------------------

async def test_message_endpoint_returns_503_on_tier1_failure():
    with patch("backend.router.api.call_tier1", AsyncMock(side_effect=Exception("LLM down"))):
        with pytest.raises(HTTPException) as exc_info:
            await message(MessageRequest(text="Hello", chat_id="chat_001"))
    assert exc_info.value.status_code == 503
    assert "unavailable" in exc_info.value.detail


# ---------------------------------------------------------------------------
# POST /message — store_reminder intent
# ---------------------------------------------------------------------------

async def test_message_endpoint_creates_reminder_on_store_reminder_intent():
    from datetime import datetime, timezone
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="",
    )
    mock_reminder = MagicMock()
    mock_reminder.text = "Call Marc"
    mock_reminder.trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    req = MessageRequest(text="Remind me to call Marc tomorrow at 10", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(return_value=mock_reminder)):
        result = await message(req)

    assert result.tier_used == 1
    assert result.intent == "store_reminder"
    assert "Call Marc" in result.response
    assert "April" in result.response


async def test_message_endpoint_returns_friendly_error_on_extraction_failure():
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Remind me blah", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(side_effect=ValueError("bad parse"))):
        result = await message(req)

    assert result.tier_used == 1
    assert result.intent == "store_reminder"
    assert "couldn't understand" in result.response


async def test_message_endpoint_does_not_escalate_store_reminder():
    """store_reminder must never call Tier 2."""
    tier1_result = Tier1Response(
        intent="store_reminder",
        complexity=0.95,  # would normally trigger escalation
        escalate=True,
        escalation_reason="",
        response="",
    )
    mock_reminder = MagicMock()
    mock_reminder.text = "Call Marc"
    from datetime import datetime, timezone
    mock_reminder.trigger_at = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    req = MessageRequest(text="Remind me to call Marc tomorrow at 10", chat_id="+33612345678")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.extract_and_save", AsyncMock(return_value=mock_reminder)), \
         patch("backend.router.api.call_tier2", AsyncMock()) as mock_t2:
        result = await message(req)

    mock_t2.assert_not_awaited()
    assert result.intent == "store_reminder"


# ---------------------------------------------------------------------------
# store_knowledge intent
# ---------------------------------------------------------------------------

async def test_message_endpoint_stores_chunks_on_store_knowledge_intent():
    from backend.memory.vector import EmbedResult
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Python is great for data science", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Python is great for data science"]), \
         patch("backend.router.api.store_chunk", return_value="fake-uuid") as mock_store:
        result = await message(req)

    assert result.response == "Saved."
    assert result.tier_used == 1
    assert result.intent == "store_knowledge"
    mock_store.assert_called_once()
    call_positional = mock_store.call_args.args
    assert call_positional[0] == "Python is great for data science"
    assert call_positional[1]["source_type"] == "whatsapp"
    assert call_positional[1]["chunk_index"] == 0


async def test_message_endpoint_returns_friendly_error_on_embed_failure():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Some note", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Some note"]), \
         patch("backend.router.api.store_chunk", side_effect=RuntimeError("Embedding unavailable")):
        result = await message(req)

    assert "embedding service unavailable" in result.response.lower()
    assert result.intent == "store_knowledge"


# ---------------------------------------------------------------------------
# GET /embed-status
# ---------------------------------------------------------------------------

async def test_embed_status_returns_ollama_info():
    from backend.memory.vector import EmbedResult
    from backend.router.api import embed_status

    mock_result = EmbedResult(vector=[0.1] * 768, model="nomic-embed-text", source="ollama")
    with patch("backend.router.api.embed", return_value=mock_result):
        result = await embed_status()

    assert result == {"model": "nomic-embed-text", "source": "ollama", "dimensions": 768}


async def test_embed_status_returns_503_when_embedding_unavailable():
    from fastapi import HTTPException
    from backend.router.api import embed_status

    with patch("backend.router.api.embed", side_effect=RuntimeError("Embedding unavailable")):
        with pytest.raises(HTTPException) as exc_info:
            await embed_status()
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# query intent — context injection
# ---------------------------------------------------------------------------

async def test_message_endpoint_injects_context_on_query_with_results():
    tier1_initial = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer without context",
    )
    tier1_enriched = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer with context",
    )
    search_results = [{"text": "Python is great for data science", "source_type": "whatsapp"}]
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(side_effect=[tier1_initial, tier1_enriched])

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", return_value=search_results):
        result = await message(req)

    assert result.response == "Answer with context"
    assert call_tier1_mock.call_count == 2
    second_call_text = call_tier1_mock.call_args_list[1].args[0]
    assert "Python is great for data science" in second_call_text
    assert "What language for data?" in second_call_text


async def test_message_endpoint_skips_context_injection_when_no_results():
    tier1_result = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Answer without context",
    )
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(return_value=tier1_result)

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", return_value=[]):
        result = await message(req)

    assert call_tier1_mock.call_count == 1
    assert result.response == "Answer without context"


async def test_message_endpoint_continues_on_search_failure():
    """If search() raises, the query proceeds without context injection."""
    tier1_result = Tier1Response(
        intent="query",
        complexity=0.3,
        escalate=False,
        escalation_reason="",
        response="Fallback answer",
    )
    req = MessageRequest(text="What language for data?", chat_id="chat_001")

    call_tier1_mock = AsyncMock(return_value=tier1_result)

    with patch("backend.router.api.call_tier1", call_tier1_mock), \
         patch("backend.router.api.search", side_effect=Exception("Qdrant down")):
        result = await message(req)

    assert call_tier1_mock.call_count == 1
    assert result.response == "Fallback answer"


# ---------------------------------------------------------------------------
# store_knowledge — URL auto-detection
# ---------------------------------------------------------------------------

async def test_store_knowledge_routes_to_ingest_url_when_url_in_text():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Save this https://example.com/article", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_url", AsyncMock(return_value=5)) as mock_ingest:
        result = await message(req)

    mock_ingest.assert_awaited_once_with("https://example.com/article")
    assert "5" in result.response
    assert result.intent == "store_knowledge"


async def test_store_knowledge_routes_to_ingest_youtube_for_youtube_url():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(
        text="Watch this https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        chat_id="chat_001",
    )

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_youtube", AsyncMock(return_value=8)) as mock_yt:
        result = await message(req)

    mock_yt.assert_awaited_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "8" in result.response


async def test_store_knowledge_falls_back_to_text_when_no_url():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Python is great for data science", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api._chunk", return_value=["Python is great for data science"]), \
         patch("backend.router.api.store_chunk", return_value="uuid") as mock_store:
        result = await message(req)

    mock_store.assert_called_once()
    assert result.response == "Saved."


async def test_store_knowledge_url_ingestion_error_returns_friendly_message():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Save https://example.com", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_url", AsyncMock(side_effect=ValueError("insufficient content"))):
        result = await message(req)

    assert "Could not ingest" in result.response


async def test_store_knowledge_strips_trailing_punctuation_from_url():
    tier1_result = Tier1Response(
        intent="store_knowledge",
        complexity=0.2,
        escalate=False,
        escalation_reason="",
        response="",
    )
    req = MessageRequest(text="Save https://example.com/article.", chat_id="chat_001")

    with patch("backend.router.api.call_tier1", AsyncMock(return_value=tier1_result)), \
         patch("backend.router.api.ingest_url", AsyncMock(return_value=3)) as mock_ingest:
        result = await message(req)

    mock_ingest.assert_awaited_once_with("https://example.com/article")
    assert "3" in result.response
