from anthropic import AsyncAnthropic
from sqlalchemy import text

from backend.config import settings
from backend.db import AsyncSessionLocal
from backend.router.intent import Tier1Response

# Intents that always trigger escalation (may be returned outside the standard enum)
ESCALATION_INTENTS = {"synthesize", "analyze", "compare"}

SONNET_MODEL = "claude-sonnet-4-6"

TIER2_SYSTEM_PROMPT = (
    "You are a knowledgeable personal assistant helping the user manage their second brain. "
    "Provide a comprehensive, accurate, and helpful response. "
    "If a Tier-1 analysis is included in the message, use it as context but improve upon it."
)


def should_escalate(result: Tier1Response) -> bool:
    return (
        result.complexity > 0.7
        or result.intent in ESCALATION_INTENTS
        or result.escalate
    )


async def call_tier2(message: str, tier1: Tier1Response) -> str:
    """Call claude-sonnet-4-6 with the original message and Tier 1's partial response as context."""
    context_block = (
        f"\n\n[Tier-1 analysis: {tier1.response}]" if tier1.response else ""
    )
    user_content = f"{message}{context_block}"

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=SONNET_MODEL,
        max_tokens=1024,
        system=TIER2_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


async def log_escalation(message: str, reason: str, chat_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO escalations (message, reason, chat_id) "
                "VALUES (:message, :reason, :chat_id)"
            ),
            {"message": message, "reason": reason, "chat_id": chat_id},
        )
        await session.commit()
