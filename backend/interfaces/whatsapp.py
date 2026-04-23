import logging
import re
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from fastapi import APIRouter, BackgroundTasks, Form, Header, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from backend.config import settings
from backend.ingestion.registry import registry
from backend.router.api import MessageRequest
from backend.router.api import message as handle_message
from backend.router.ingest import run_ingest

logger = logging.getLogger(__name__)
router = APIRouter()

_URL_RE = re.compile(r"https?://[^\s]+")
_YT_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be"}
_PROCESSING_MSG = "Got it, I'm processing that — I'll let you know when it's ready."


def _classify_url(url: str) -> str:
    return "youtube" if urlparse(url).netloc in _YT_DOMAINS else "url"


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(""),
    From: str = Form(...),
    x_twilio_signature: str = Header(...),
    MediaUrl0: str | None = Form(None),
    MediaContentType0: str | None = Form(None),
) -> Response:
    validator = RequestValidator(settings.twilio_auth_token)
    params = dict(await request.form())
    if not validator.validate(str(request.url), params, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    chat_id = From.removeprefix("whatsapp:")

    # PDF media attachment from Twilio
    if MediaUrl0 and MediaContentType0 == "application/pdf":
        task_id = registry.create()
        background_tasks.add_task(
            run_ingest,
            task_id,
            "pdf",
            MediaUrl0,
            chat_id,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
        twiml = f"<Response><Message>{escape(_PROCESSING_MSG)}</Message></Response>"
        return Response(content=twiml, media_type="text/xml")

    # URL detected in message body
    url_match = _URL_RE.search(Body)
    if url_match:
        url = url_match.group(0).rstrip(".,;:!?)\"'")
        source_type = _classify_url(url)
        task_id = registry.create()
        background_tasks.add_task(run_ingest, task_id, source_type, url, chat_id)
        twiml = f"<Response><Message>{escape(_PROCESSING_MSG)}</Message></Response>"
        return Response(content=twiml, media_type="text/xml")

    # Normal message flow
    result = await handle_message(MessageRequest(text=Body, chat_id=chat_id))
    twiml = f"<Response><Message>{escape(result.response)}</Message></Response>"
    return Response(content=twiml, media_type="text/xml")
