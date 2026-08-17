from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_sqlite_schema() -> None:
    """Apply small additive migrations for databases created by earlier builds."""
    if settings.database_url.startswith("postgresql"):
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) NOT NULL DEFAULT 'text'"))
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS external_id VARCHAR(120) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS external_status VARCHAR(30) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS sender_email VARCHAR(320) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ NULL"))
            connection.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS time_zone VARCHAR(60) NOT NULL DEFAULT 'Europe/Paris'"))
            connection.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email_subject VARCHAR(240) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email_message TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS whatsapp_message TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS sms_message VARCHAR(160) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS tags VARCHAR(500) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS email_subject VARCHAR(240) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS email_message TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS whatsapp_message TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS sms_message VARCHAR(160) NOT NULL DEFAULT ''"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS quality_score INTEGER NOT NULL DEFAULT 0"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) NOT NULL DEFAULT 'pending'"))
            connection.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS validation_notes TEXT NOT NULL DEFAULT ''"))
        return
    if not settings.database_url.startswith("sqlite"):
        return
    required = {
        "campaigns": {
            "sector": "VARCHAR(120) NOT NULL DEFAULT ''",
            "objective": "VARCHAR(120) NOT NULL DEFAULT 'book_meeting'",
            "tags": "VARCHAR(500) NOT NULL DEFAULT ''",
            "content_type": "VARCHAR(20) NOT NULL DEFAULT 'text'",
            "external_id": "VARCHAR(120) NOT NULL DEFAULT ''",
            "external_status": "VARCHAR(30) NOT NULL DEFAULT ''",
            "sender_email": "VARCHAR(320) NOT NULL DEFAULT ''",
            "scheduled_at": "DATETIME NULL",
            "time_zone": "VARCHAR(60) NOT NULL DEFAULT 'Europe/Paris'",
        },
        "contacts": {
            "score": "INTEGER NOT NULL DEFAULT 50",
            "tags": "VARCHAR(500) NOT NULL DEFAULT ''",
            "custom_data": "JSON NOT NULL DEFAULT '{}'",
            "email_subject": "VARCHAR(240) NOT NULL DEFAULT ''",
            "email_message": "TEXT NOT NULL DEFAULT ''",
            "whatsapp_message": "TEXT NOT NULL DEFAULT ''",
            "sms_message": "VARCHAR(160) NOT NULL DEFAULT ''",
        },
        "prospects": {
            "description": "TEXT NOT NULL DEFAULT ''",
            "tags": "VARCHAR(500) NOT NULL DEFAULT ''",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "email_subject": "VARCHAR(240) NOT NULL DEFAULT ''",
            "email_message": "TEXT NOT NULL DEFAULT ''",
            "whatsapp_message": "TEXT NOT NULL DEFAULT ''",
            "sms_message": "VARCHAR(160) NOT NULL DEFAULT ''",
            "quality_score": "INTEGER NOT NULL DEFAULT 0",
            "validation_status": "VARCHAR(30) NOT NULL DEFAULT 'pending'",
            "validation_notes": "TEXT NOT NULL DEFAULT ''",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table, columns in required.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))
