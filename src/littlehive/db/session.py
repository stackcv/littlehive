from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def create_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True), engine


def init_db(database_url: str) -> None:
    factory, engine = create_session_factory(database_url)
    _ = factory
    from littlehive.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
