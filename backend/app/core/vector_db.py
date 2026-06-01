import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import config

logger = logging.getLogger(__name__)


def _build_vector_db_url() -> str:
    password = config.vector_db_password.get_secret_value()
    return (
        f"postgresql+psycopg2://{config.vector_db_username}:{password}"
        f"@{config.vector_db_host}:{config.vector_db_port}/{config.vector_db_name}"
    )


VECTOR_DATABASE_URL = _build_vector_db_url()

vector_engine = create_engine(
    url=VECTOR_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_use_lifo=True,
    echo=False,
    connect_args={
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)

VectorSession = sessionmaker(bind=vector_engine, autocommit=False, autoflush=False)


def check_vector_extension() -> bool:
    try:
        with vector_engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
            return result.fetchone() is not None
    except SQLAlchemyError as e:
        logger.warning("Failed to check pgvector extension: %s", e)
        return False


def init_vector_db() -> None:
    try:
        with vector_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            logger.info("pgvector extension ensured")
    except SQLAlchemyError as e:
        logger.warning("Could not create pgvector extension: %s", e)


def get_vector_session() -> Generator[Session, None, None]:
    session = VectorSession()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()
