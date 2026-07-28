from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


def _engine_kwargs() -> dict:
    url = (settings.database_url or "").strip()
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs

    if url.startswith("postgresql"):
        connect_args: dict = {"connect_timeout": int(settings.db_connect_timeout or 10)}
        sslmode = (settings.db_sslmode or "").strip()
        if sslmode and "sslmode=" not in url.lower():
            connect_args["sslmode"] = sslmode
        kwargs["connect_args"] = connect_args
        # Pool knobs matter under multi-worker / managed Postgres connection caps.
        kwargs["pool_size"] = max(1, int(settings.db_pool_size or 5))
        kwargs["max_overflow"] = max(0, int(settings.db_max_overflow or 10))
        kwargs["pool_recycle"] = max(60, int(settings.db_pool_recycle or 1800))
        kwargs["pool_timeout"] = max(1, int(settings.db_pool_timeout or 30))
    return kwargs


engine = create_engine(settings.database_url, **_engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
