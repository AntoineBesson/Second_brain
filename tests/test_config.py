# tests/test_config.py
import pytest
from pydantic import ValidationError
from backend.config import Settings


def test_settings_raises_on_missing_database_url(monkeypatch):
    # BaseSettings reads from environment as fallback, so unset to test validation
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            anthropic_api_key="k",
            openai_api_key="k",
            twilio_account_sid="k",
            twilio_auth_token="k",
            twilio_whatsapp_from="whatsapp:+1",
            # database_url intentionally omitted
            qdrant_url="http://localhost:6333",
            ollama_url="http://localhost:11434",
        )


def test_settings_accepts_all_fields():
    s = Settings(
        anthropic_api_key="a",
        openai_api_key="b",
        twilio_account_sid="c",
        twilio_auth_token="d",
        twilio_whatsapp_from="whatsapp:+1",
        database_url="postgresql+asyncpg://u:p@h:5432/db",
        qdrant_url="http://localhost:6333",
        ollama_url="http://localhost:11434",
    )
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
