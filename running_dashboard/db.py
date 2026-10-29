from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Float, Text, ForeignKey,
    UniqueConstraint, Index, create_engine, event, select, text,
)
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

metadata = MetaData()

activities = Table(
    "activities", metadata,
    Column("activity_id", String(100), primary_key=True),
    Column("activity_date", String(64), index=True),
    Column("activity_name", String(500)),
    Column("activity_type", String(100), index=True),
    Column("distance_km", Float),
    Column("moving_time_s", Float),
    Column("elapsed_time_s", Float),
    Column("elevation_gain_m", Float),
    Column("avg_hr", Float),
    Column("max_hr", Float),
    Column("avg_speed_mps", Float),
    Column("max_speed_mps", Float),
    Column("avg_cadence", Float),
    Column("calories", Float),
    Column("relative_effort", Float),
    Column("avg_power_w", Float),
    Column("max_power_w", Float),
    Column("suffer_score", Float),
    Column("raw_json", Text),
    Column("updated_at", String(64)),
)

activity_points = Table(
    "activity_points", metadata,
    Column("point_id", Integer, primary_key=True, autoincrement=True),
    Column("activity_id", String(100), ForeignKey("activities.activity_id", ondelete="CASCADE"), nullable=False),
    Column("point_index", Integer, nullable=False),
    Column("timestamp", String(64)),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("altitude_m", Float),
    Column("distance_m", Float),
    Column("heart_rate", Float),
    Column("cadence", Float),
    Column("speed_mps", Float),
    Column("power_w", Float),
    Column("temperature_c", Float),
    Column("grade_percent", Float),
    Column("raw_json", Text),
    UniqueConstraint("activity_id", "point_index", name="uq_points_activity_index"),
)
Index("ix_points_activity", activity_points.c.activity_id)
Index("ix_points_timestamp", activity_points.c.timestamp)

import_state = Table(
    "import_state", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", Text),
)

_engine: Engine | None = None


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    db_path = PROJECT_ROOT / "data" / "running.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        kwargs = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite:"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite:"):
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
    return _engine


def init_db() -> None:
    metadata.create_all(get_engine())


def get_table_df(table: Table):
    import pandas as pd
    with get_engine().connect() as conn:
        return pd.read_sql(select(table), conn)


def get_count(table: Table) -> int:
    with get_engine().connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar_one())
