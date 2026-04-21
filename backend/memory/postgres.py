from sqlalchemy import Boolean, Column, Integer, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    text = Column(Text, nullable=False)
    trigger_at = Column(TIMESTAMP(timezone=True), nullable=False)
    sent = Column(Boolean, nullable=False, server_default=sql_text("false"))
    chat_id = Column(Text, nullable=False)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    title = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    source_url = Column(Text)
    date_added = Column(TIMESTAMP(timezone=True), nullable=False, server_default=sql_text("now()"))
    chunk_index = Column(Integer, nullable=False, server_default=sql_text("0"))


class ApiTool(Base):
    __tablename__ = "api_tools"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    name = Column(Text, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    base_url = Column(Text, nullable=False)
    spec = Column(JSONB, nullable=False)
    auth_type = Column(Text, nullable=False)
    auth_secret_env = Column(Text)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()"))
    message = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    escalated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=sql_text("now()"))
