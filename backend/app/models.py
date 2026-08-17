from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(20), default="email")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    subject: Mapped[str] = mapped_column(String(240), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    calendar_url: Mapped[str] = mapped_column(String(500), default="")
    video_url: Mapped[str] = mapped_column(String(500), default="")
    provider: Mapped[str] = mapped_column(String(30), default="emelia")
    sector: Mapped[str] = mapped_column(String(120), default="")
    objective: Mapped[str] = mapped_column(String(120), default="book_meeting")
    tags: Mapped[str] = mapped_column(String(500), default="")
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    external_id: Mapped[str] = mapped_column(String(120), default="")
    external_status: Mapped[str] = mapped_column(String(30), default="")
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_zone: Mapped[str] = mapped_column(String(60), default="Europe/Paris")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    contacts: Mapped[list["Contact"]] = relationship(cascade="all, delete-orphan", back_populates="campaign")
    steps: Mapped[list["SequenceStep"]] = relationship(cascade="all, delete-orphan", back_populates="campaign", order_by="SequenceStep.position")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("campaign_id", "dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    business_name: Mapped[str] = mapped_column(String(240), default="")
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(180), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="ready")
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=50)
    tags: Mapped[str] = mapped_column(String(500), default="")
    custom_data: Mapped[dict] = mapped_column(JSON, default=dict)
    email_subject: Mapped[str] = mapped_column(String(240), default="")
    email_message: Mapped[str] = mapped_column(Text, default="")
    whatsapp_message: Mapped[str] = mapped_column(Text, default="")
    sms_message: Mapped[str] = mapped_column(String(160), default="")
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="contacts")


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    provider: Mapped[str] = mapped_column(String(30), default="emelia")
    delay_hours: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(240), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    stop_on_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    campaign: Mapped[Campaign] = relationship(back_populates="steps")


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(240), default="")
    message: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(120), default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    state: Mapped[str] = mapped_column(String(30), default="open")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    rendered_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Suppression(Base):
    __tablename__ = "suppressions"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(240), default="opt-out")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(30), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProspectingJob(Base):
    __tablename__ = "prospecting_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(240))
    location: Mapped[str] = mapped_column(String(240), default="")
    requested_limit: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    email_scraped_count: Mapped[int] = mapped_column(Integer, default=0)
    email_enriched_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("prospecting_jobs.id"), index=True, nullable=True)
    business_name: Mapped[str] = mapped_column(String(240), default="")
    category: Mapped[str] = mapped_column(String(240), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    city: Mapped[str] = mapped_column(String(160), default="")
    country: Mapped[str] = mapped_column(String(10), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    email_source: Mapped[str] = mapped_column(String(30), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    google_maps_url: Mapped[str] = mapped_column(String(1000), default="")
    place_id: Mapped[str] = mapped_column(String(240), default="")
    rating: Mapped[str] = mapped_column(String(30), default="")
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    decision_maker_name: Mapped[str] = mapped_column(String(240), default="")
    decision_maker_role: Mapped[str] = mapped_column(String(180), default="")
    decision_maker_linkedin: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    email_subject: Mapped[str] = mapped_column(String(240), default="")
    email_message: Mapped[str] = mapped_column(Text, default="")
    whatsapp_message: Mapped[str] = mapped_column(Text, default="")
    sms_message: Mapped[str] = mapped_column(String(160), default="")
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    validation_status: Mapped[str] = mapped_column(String(30), default="pending")
    validation_notes: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(30), default="new")
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
