"""Read-only PostgreSQL connection check."""

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


def check_database_connection() -> bool:
    """Run SELECT 1 without creating or modifying database objects."""

    database_engine: Engine | None = None
    try:
        from app.db.session import engine

        database_engine = engine
        with database_engine.connect() as connection:
            return connection.scalar(text("SELECT 1")) == 1
    except (RuntimeError, SQLAlchemyError):
        return False
    finally:
        if database_engine is not None:
            database_engine.dispose()


if __name__ == "__main__":
    if check_database_connection():
        print("PostgreSQL connection to studymate_ai_db succeeded.")
        raise SystemExit(0)

    print(
        "PostgreSQL connection failed. Check DATABASE_URL and the PostgreSQL service."
    )
    raise SystemExit(1)
