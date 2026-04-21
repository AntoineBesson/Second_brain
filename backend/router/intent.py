import json
from dataclasses import dataclass

import httpx
from anthropic import AsyncAnthropic

from backend.config import settings

SYSTEM_PROMPT = (
    "You are a personal assistant intent classifier. "
    "Analyze the user message and respond with ONLY valid JSON — no markdown, no explanation:\n"
    '{\n'
    '  "intent": "<one of: store_reminder, store_knowledge, query, recall, tool_call, general>",\n'
    '  "complexity": <float 0.0-1.0>,\n'
    '  "escalate": <true|false>,\n'
    '  "escalation_reason": "<empty string if not escalating>",\n'
    '  "response": "<your response to the user>"\n'
    "}"
)


@dataclass
class Tier1Response:
    intent: str
    complexity: float
    escalate: bool
    escalation_reason: str
    response: str


async def call_tier1(message: str) -> Tier1Response:
    """Call Tier 1 (Ollama gemma3:4b). Falls back to Haiku if Ollama is unavailable."""
    try:
        return await _call_ollama(message)
    except Exception:
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
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return _parse_response(response.content[0].text)


def _parse_response(content: str) -> Tier1Response:
    data = json.loads(content)
    return Tier1Response(
        intent=data["intent"],
        complexity=float(data["complexity"]),
        escalate=bool(data["escalate"]),
        escalation_reason=data.get("escalation_reason", ""),
        response=data["response"],
    )
