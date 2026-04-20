from sqlalchemy import inspect

from backend.memory.postgres import ApiTool, KnowledgeItem, Reminder


def test_reminder_columns():
    cols = {c.key for c in inspect(Reminder).columns}
    assert cols == {"id", "text", "trigger_at", "sent", "chat_id"}


def test_knowledge_item_columns():
    cols = {c.key for c in inspect(KnowledgeItem).columns}
    assert cols == {"id", "title", "source_type", "source_url", "date_added", "chunk_index"}


def test_api_tool_columns():
    cols = {c.key for c in inspect(ApiTool).columns}
    assert cols == {"id", "name", "description", "base_url", "spec", "auth_type", "auth_secret_env"}


def test_api_tool_name_is_unique():
    name_col = inspect(ApiTool).columns["name"]
    assert name_col.unique
