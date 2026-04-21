import json
from dataclasses import dataclass

import httpx
from anthropic import AsyncAnthropic

from backend.config import settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    'You are a personal assistant intent classifier. '
    'Analyze the user message and respond with ONLY a raw JSON object — '
    'no markdown, no code fences, no explanation.\n\n'
    'The JSON must have exactly these fields:\n'
    '{\n'
    '  "intent": <one of the strings: store_reminder, store_knowledge, query, recall, tool_call, general>,\n'
    '  "complexity": <a float between 0.0 and 1.0>,\n'
    '  "escalate": <true or false>,\n'
    '  "escalation_reason": <empty string if not escalating, else brief reason>,\n'
    '  "response": <your response to the user>\n'
    '}\n\n'
    '"intent" must be exactly one of: store_reminder, store_knowledge, query, recall, tool_call, general\n'
    'Do not use any other intent value.'
)


@dataclass
class Tier1Response:
    intent: str
    complexity: float
    escalate: bool
    escalation_reason: str
    response: str


async def call_tier1(message: str) -> Tier1Response:
    """Call Tier 1 (Ollama gemma3:4b). Falls back to Haiku if Ollama is unreachable."""
    try:
        return await _call_ollama(message)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return await _call_haiku_fallback(message)


async def _call_ollama(message: str) -> Tier1Response:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": "gemma3:4b",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "stream": False,
                "format": "json",
            },
        )
        r.raise_for_status()
    content = r.json()["message"]["content"]
    return _parse_response(content)


async def _call_haiku_fallback(message: str) -> Tier1Response:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return _parse_response(response.content[0].text)


def _parse_response(content: str) -> Tier1Response:
    try:
        data = json.loads(content)
        return Tier1Response(
            intent=data["intent"],
            complexity=max(0.0, min(1.0, float(data["complexity"]))),
            escalate=str(data.get("escalate", False)).lower() == "true",
            escalation_reason=data.get("escalation_reason", ""),
            response=data["response"],
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc!r}. Raw content: {content!r}") from exc
