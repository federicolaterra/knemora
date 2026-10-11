from pathlib import Path

from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import create_engine, text

from app.config import get_settings


def test_milestone_07_database_upgrades_without_losing_data(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    database_path = tmp_path / "milestone-07.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("KNEMORA_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "5fd2a7619c10")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, display_name, is_active, password_hash, failed_login_count) "
                "VALUES (:id, :email, :name, 1, NULL, 0)"
            ),
            {
                "id": "00000000000000000000000000000001",
                "email": "existing@example.test",
                "name": "Existing User",
            },
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM users")) == 1
        version = connection.execute(
            text(
                "SELECT app_version, schema_version, knowledge_schema_version "
                "FROM application_versions WHERE component = 'core'"
            )
        ).one()
        assert tuple(version) == ("0.8.4", 11, 1)

    engine.dispose()
    get_settings.cache_clear()
