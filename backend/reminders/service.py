from backend.db import AsyncSessionLocal
from backend.memory.postgres import Reminder
from backend.reminders.crud import create_reminder, get_or_create_user_prefs
from backend.reminders.extraction import call_tier1_extract, parse_datetime


async def extract_and_save(text: str, chat_id: str) -> Reminder:
    """Extract reminder details from text and persist to DB.

    Raises ValueError if extraction or datetime parsing fails.
    """
    async with AsyncSessionLocal() as session:
        prefs = await get_or_create_user_prefs(session, chat_id)
        extracted = await call_tier1_extract(text)
        trigger_at = parse_datetime(extracted["datetime_str"], prefs.timezone)
        reminder = await create_reminder(session, extracted["reminder_text"], trigger_at, chat_id)
        await session.commit()
        return reminder
