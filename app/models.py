from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from app.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    hunting_active = Column(Boolean, default=False, nullable=False)
    ai_provider = Column(String(30), default="groq", nullable=False)
    target_cities = Column(String(255), default="Islamabad,Rawalpindi", nullable=False)
    daily_email_limit = Column(Integer, default=25, nullable=False)
    daily_whatsapp_limit = Column(Integer, default=15, nullable=False)
    require_approval_for_quotes = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ServiceCatalog(Base):
    __tablename__ = "services_catalog"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, unique=True, nullable=False)
    name = Column(String(150), unique=True, nullable=False)
    category = Column(String(80), nullable=False)
    summary = Column(Text, nullable=False)
    ideal_client_profile = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(200), nullable=False, index=True)
    website = Column(String(300), nullable=True)
    email = Column(String(200), nullable=True, index=True)
    phone = Column(String(60), nullable=True, index=True)
    category = Column(String(120), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    country = Column(String(100), default="Pakistan")
    decision_maker = Column(String(200), nullable=True)
    source = Column(String(80), default="openstreetmap")
    dedup_hash = Column(String(128), unique=True, nullable=False, index=True)

    research_summary = Column(Text, nullable=True)
    identified_needs = Column(Text, nullable=True)
    matched_service_id = Column(Integer, ForeignKey("services_catalog.id"), nullable=True)
    match_reason = Column(Text, nullable=True)

    status = Column(String(50), default="discovered", index=True)
    whatsapp_opted_in = Column(Boolean, default=False, nullable=False)
    is_suppressed = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    channel = Column(String(30), nullable=False)
    subject = Column(String(255), nullable=True)
    body = Column(Text, nullable=False)
    status = Column(String(30), default="draft")
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    channel = Column(String(30), nullable=False)
    direction = Column(String(20), nullable=False)
    intent = Column(String(60), nullable=True)
    message_text = Column(Text, nullable=False)
    needs_human_attention = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SuppressionList(Base):
    __tablename__ = "suppression_list"

    id = Column(Integer, primary_key=True, index=True)
    contact_value = Column(String(200), unique=True, nullable=False, index=True)
    channel = Column(String(30), default="all")
    reason = Column(String(120), default="opt_out")
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentJobLog(Base):
    __tablename__ = "agent_job_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(100), nullable=False, index=True)
    status = Column(String(30), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String(100), default="system")
    action = Column(String(150), nullable=False)
    target_type = Column(String(80), nullable=True)
    target_id = Column(String(80), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
