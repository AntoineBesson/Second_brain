from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI

from backend.db import engine
from backend.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run pending migrations synchronously before serving any requests.
    # Blocking I/O here is intentional — no requests are in-flight at startup.
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    yield
    await engine.dispose()


app = FastAPI(title="Second Brain", lifespan=lifespan)
app.include_router(health_router)
