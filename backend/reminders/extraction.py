import json
from datetime import datetime

import dateparser
import httpx
from anthropic import AsyncAnthropic

from backend.config import settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"

EXTRACTION_SYSTEM_PROMPT = (
    "You are a reminder extraction assistant. "
    "Given a user message, extract the reminder text and the time expression. "
    "Respond with ONLY a raw JSON object — no markdown, no code fences, no explanation.\n\n"
    "{\n"
    '  "reminder_text": <the thing to be reminded about, e.g. "Call Marc">,\n'
    '  "datetime_str": <the time expression exactly as the user said it, e.g. "tomorrow at 10">\n'
    "}\n"
)


async def call_tier1_extract(text: str) -> dict:
    """Call Ollama for extraction. Falls back to Haiku on connection error."""
    try:
        return await _extract_ollama(text)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return await _extract_haiku(text)


async def _extract_ollama(text: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": "gemma3:4b",
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "format": "json",
            },
        )
        r.raise_for_status()
    return _parse_extraction(r.json()["message"]["content"])


async def _extract_haiku(text: str) -> dict:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=256,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    return _parse_extraction(response.content[0].text)


def _parse_extraction(content: str) -> dict:
    try:
        data = json.loads(content)
        if "reminder_text" not in data or "datetime_str" not in data:
            raise KeyError("missing required fields")
        return {
            "reminder_text": str(data["reminder_text"]),
            "datetime_str": str(data["datetime_str"]),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Failed to parse extraction response: {exc!r}. Raw: {content!r}"
        ) from exc


def parse_datetime(datetime_str: str, timezone: str) -> datetime:
    dt = dateparser.parse(
        datetime_str,
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if dt is None:
        raise ValueError(f"Could not parse datetime: {datetime_str!r}")
    return dt
