from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    openai_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    database_url: str
    qdrant_url: str
    ollama_url: str

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
