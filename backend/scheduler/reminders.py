import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.db import AsyncSessionLocal
from backend.reminders.crud import get_due_reminders, mark_sent

logger = logging.getLogger(__name__)


async def dispatch_due_reminders() -> None:
    async with AsyncSessionLocal() as session:
        reminders = await get_due_reminders(session)
        for reminder in reminders:
            try:
                await _send_whatsapp(reminder.text, reminder.chat_id)
                await mark_sent(session, reminder.id)
                await session.commit()
            except Exception as exc:
                logger.warning("Failed to dispatch reminder %s: %s", reminder.id, exc)


async def _send_whatsapp(text: str, chat_id: str) -> None:
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts"
        f"/{settings.twilio_account_sid}/Messages.json"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            url,
            data={
                "Body": text,
                "From": settings.twilio_whatsapp_from,
                "To": f"whatsapp:{chat_id}",
            },
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
        r.raise_for_status()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(dispatch_due_reminders, "interval", seconds=60)
    return scheduler
