from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.postgres import Reminder, UserPreference


async def create_reminder(
    session: AsyncSession,
    text_: str,
    trigger_at: datetime,
    chat_id: str,
) -> Reminder:
    reminder = Reminder(text=text_, trigger_at=trigger_at, chat_id=chat_id)
    session.add(reminder)
    await session.flush()
    await session.refresh(reminder)
    return reminder


async def get_due_reminders(session: AsyncSession) -> list[Reminder]:
    result = await session.execute(
        select(Reminder).where(
            Reminder.trigger_at <= func.now(),
            Reminder.sent == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def mark_sent(session: AsyncSession, reminder_id) -> None:
    await session.execute(
        update(Reminder).where(Reminder.id == reminder_id).values(sent=True)
    )


async def get_or_create_user_prefs(
    session: AsyncSession, chat_id: str
) -> UserPreference:
    await session.execute(
        text(
            "INSERT INTO user_preferences (chat_id) "
            "VALUES (:chat_id) ON CONFLICT DO NOTHING"
        ),
        {"chat_id": chat_id},
    )
    result = await session.execute(
        select(UserPreference).where(UserPreference.chat_id == chat_id)
    )
    return result.scalar_one()
