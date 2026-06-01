from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

from .config import config


def _build_mysql_url() -> str:
    credentials = f"{config.database_username}:{config.database_password.get_secret_value()}"
    host = config.database_socket or f"{config.database_host}:{config.database_port}"
    if config.database_socket:
        return f"{config.database_type}+{config.connector}://{credentials}@localhost/{config.database_name}?unix_socket={config.database_socket}"
    return f"{config.database_type}+{config.connector}://{credentials}@{host}/{config.database_name}"


DATABASE_URL = _build_mysql_url()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    url=DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

sessionLocal = sessionmaker(autocommit=False, bind=engine, autoflush=False)


def get_session() -> Generator[Session, None, None]:
    db = sessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
