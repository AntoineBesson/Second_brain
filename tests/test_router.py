# tests/test_router.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.router.intent import Tier1Response, _call_haiku_fallback, _call_ollama, _parse_response, call_tier1
from backend.router.escalation import call_tier2, log_escalation, should_escalate


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
