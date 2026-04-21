from sqlalchemy import inspect

from backend.memory.postgres import ApiTool, Escalation, KnowledgeItem, Reminder


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


def test_escalation_columns():
    cols = {c.key for c in inspect(Escalation).columns}
    assert cols == {"id", "message", "reason", "chat_id", "escalated_at"}


def test_escalation_timestamp_defaults():
    ts_col = inspect(Escalation).columns["escalated_at"]
    assert not ts_col.nullable
    assert ts_col.server_default is not None
