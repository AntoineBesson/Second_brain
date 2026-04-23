import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.memory.vector import _chunk, embed, search, store_chunk
from backend.ingestion.url import ingest_url
from backend.ingestion.youtube import ingest_youtube
from backend.reminders.service import extract_and_save
from backend.router.escalation import call_tier2, log_escalation, should_escalate
from backend.router.intent import call_tier1

logger = logging.getLogger(__name__)
_YT_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be"}
router = APIRouter()


class MessageRequest(BaseModel):
    text: str
    chat_id: str


class MessageResponse(BaseModel):
    response: str
    tier_used: int
    intent: str


@router.get("/embed-status")
async def embed_status() -> dict:
    try:
        result = embed("test")
        return {"model": result.model, "source": result.source, "dimensions": len(result.vector)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Embedding service unavailable") from exc


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

    if tier1.intent == "store_knowledge":
        url_match = re.search(r"https?://[^\s]+", req.text)
        if url_match:
            url = url_match.group(0).rstrip(".,;:!?)\"'")
            source_type = "youtube" if urlparse(url).netloc in _YT_DOMAINS else "url"
            try:
                if source_type == "youtube":
                    n = await ingest_youtube(url)
                else:
                    n = await ingest_url(url)
                response_text = f"Saved — ingested {n} chunks from {url}."
            except Exception as exc:
                response_text = f"Could not ingest URL: {exc}"
        else:
            try:
                chunks = _chunk(req.text)
                for i, chunk in enumerate(chunks):
                    store_chunk(chunk, {
                        "source_type": "whatsapp",
                        "source_url": "",
                        "title": req.text[:80],
                        "date_added": datetime.now(timezone.utc).isoformat(),
                        "chunk_index": i,
                        "tags": [],
                    })
                response_text = "Saved."
            except RuntimeError:
                response_text = "Could not save — embedding service unavailable."
            except Exception:
                response_text = "Could not save — vector store unavailable."
        return MessageResponse(response=response_text, tier_used=1, intent=tier1.intent)

    if tier1.intent == "query":
        try:
            results = search(req.text, top_k=5)
            if results:
                context_lines = "\n".join(f"- {r['text']}" for r in results)
                enriched = f"[Retrieved context:\n{context_lines}]\n\nUser query: {req.text}"
                tier1 = await call_tier1(enriched)
        except Exception as exc:
            logger.warning("Search failed, proceeding without context: %s", exc)

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
