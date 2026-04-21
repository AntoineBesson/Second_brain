import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.reminders.service import extract_and_save
from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.intent import call_tier1

logger = logging.getLogger(__name__)
router = APIRouter()


class MessageRequest(BaseModel):
    text: str
    chat_id: str


class MessageResponse(BaseModel):
    response: str
    tier_used: int
    intent: str


@router.post("/message", response_model=MessageResponse)
async def message(req: MessageRequest) -> MessageResponse:
    try:
        tier1 = await call_tier1(req.text)
    except Exception as exc:
        logger.error("Tier 1 failed: %s", exc)
        raise HTTPException(status_code=503, detail="LLM backend unavailable") from exc

    if tier1.intent == "store_reminder":
        try:
            reminder = await extract_and_save(req.text, req.chat_id)
            dt = reminder.trigger_at
            response_text = (
                f"Got it — I'll remind you to {reminder.text} "
                f"on {dt:%B} {dt.day} at {dt:%H:%M}."
            )
        except ValueError:
            response_text = "I couldn't understand when to set that reminder."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if should_escalate(tier1):
        reason = tier1.escalation_reason or f"complexity={tier1.complexity:.2f}"

        try:
            await log_escalation(req.text, reason, req.chat_id)
        except Exception as exc:
            logger.warning("Failed to log escalation: %s", exc)

        try:
            response_text = await call_tier2(req.text, tier1)
            tier_used = 2
        except Exception as exc:
            logger.warning("Tier 2 failed, falling back to Tier 1 response: %s", exc)
            response_text = tier1.response
            tier_used = 1

        return MessageResponse(response=response_text, tier_used=tier_used, intent=tier1.intent)

    return MessageResponse(response=tier1.response, tier_used=1, intent=tier1.intent)
