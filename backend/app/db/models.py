"""Modelo de datos. Toda tabla de contenido lleva user_id y se filtra por el usuario actual."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _now():
    return func.now()


class ProjectStatus(enum.StrEnum):
    """Texto en la BD (VARCHAR + validacion), no ENUM nativo: anadir un estado no exige ALTER."""

    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    DETECTING = "detecting"
    READY = "ready"
    FAILED = "failed"

    @property
    def busy(self) -> bool:
        return self in (ProjectStatus.DOWNLOADING, ProjectStatus.TRANSCRIBING, ProjectStatus.DETECTING)


_project_status = Enum(
    ProjectStatus, native_enum=False, length=16, validate_strings=True,
    values_callable=lambda e: [m.value for m in e],
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=1)
    max_video_minutes: Mapped[int] = mapped_column(Integer, default=180)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())


class YouTubeChannel(Base):
    __tablename__ = "youtube_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(8), default="es")
    seo_rules: Mapped[str] = mapped_column(Text, default="")
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet
    token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet
    yt_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    yt_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yt_thumbnail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_privacy: Mapped[str] = mapped_column(String(16), default="private")
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())


class BrandTemplate(Base):
    __tablename__ = "brand_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    preset: Mapped[str] = mapped_column(String(32), default="editorial")  # editorial | hormozi | minimal
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    fonts: Mapped[dict] = mapped_column(JSON, default=dict)
    logo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    intro: Mapped[dict] = mapped_column(JSON, default=dict)
    outro: Mapped[dict] = mapped_column(JSON, default=dict)
    sfx: Mapped[bool] = mapped_column(Boolean, default=True)
    music: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512), default="")
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    words_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    silences_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # {"A": {"name", "role", "caption_style": "sans_upper"|"serif_italic", "is_source": bool}}
    speakers: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    status: Mapped[ProjectStatus] = mapped_column(_project_status, default=ProjectStatus.DOWNLOADING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True
    )
    default_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand_templates.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())

    clips: Mapped[list[Clip]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    transcript: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(String(255), default="")
    emphasis_json: Mapped[list] = mapped_column(JSON, default=list)
    # Partes tematicas del clip, una frase cada una (§4.1 del md).
    parts: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    graphics_json: Mapped[list] = mapped_column(JSON, default=list)
    intro_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    outro_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand_templates.id", ondelete="SET NULL"), nullable=True
    )
    layout: Mapped[str] = mapped_column(String(16), default="split")  # split | full | facecam
    focus: Mapped[str] = mapped_column(String(16), default="center")
    zoom: Mapped[float] = mapped_column(Float, default=1.0)
    top_ratio: Mapped[float] = mapped_column(Float, default=0.5)
    # detected | approved | planning | rendering | rendered | uploading | uploaded | failed
    status: Mapped[str] = mapped_column(String(16), default="detected")
    rendered_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    seo_title: Mapped[str] = mapped_column(String(255), default="")
    seo_description: Mapped[str] = mapped_column(Text, default="")
    seo_tags: Mapped[str] = mapped_column(Text, default="")
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True
    )
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy: Mapped[str] = mapped_column(String(16), default="private")
    publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())

    project: Mapped[Project] = relationship(back_populates="clips")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_queue", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(24))  # ingest | detect | plan_graphics | render | upload
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # queued | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    log_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=_now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
