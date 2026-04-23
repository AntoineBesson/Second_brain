from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router
from backend.router.ingest import router as ingest_router
from backend.interfaces.whatsapp import router as whatsapp_router
from backend.router.api import router as message_router
from backend.scheduler.reminders import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()
    await engine.dispose()


app = FastAPI(title="Second Brain", lifespan=lifespan)
app.include_router(health_router)
app.include_router(message_router)
app.include_router(whatsapp_router)
app.include_router(ingest_router)
