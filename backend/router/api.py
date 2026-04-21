from fastapi import APIRouter
from pydantic import BaseModel

from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.intent import call_tier1

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
    tier1 = await call_tier1(req.text)

    if should_escalate(tier1):
        reason = tier1.escalation_reason or f"complexity={tier1.complexity:.2f}"
        await log_escalation(req.text, reason, req.chat_id)
        response_text = await call_tier2(req.text, tier1)
        return MessageResponse(response=response_text, tier_used=2, intent=tier1.intent)

    return MessageResponse(response=tier1.response, tier_used=1, intent=tier1.intent)
