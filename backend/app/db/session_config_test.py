"""Migration configuration preserves encoded database credentials and sockets."""

import pytest
from sqlalchemy.engine import make_url

from app.db import session as db_session


def test_alembic_preserves_percent_encoded_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+asyncpg://owner:pa%25ss%40word@localhost/initiative"
    monkeypatch.setattr(db_session.settings, "DATABASE_URL", url)

    configured = db_session._get_alembic_config().get_main_option("sqlalchemy.url")

    assert configured == url
    assert configured is not None
    assert make_url(configured).password == "pa%ss@word"


def test_alembic_preserves_percent_encoded_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+asyncpg://owner@/initiative?host=%2Ftmp%2Finitiative-postgres"
    monkeypatch.setattr(db_session.settings, "DATABASE_URL", url)

    configured = db_session._get_alembic_config().get_main_option("sqlalchemy.url")

    assert configured == url
    assert configured is not None
    assert make_url(configured).query["host"] == "/tmp/initiative-postgres"


def test_alembic_preserves_plain_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+asyncpg://owner:fixture@localhost:5432/initiative"
    monkeypatch.setattr(db_session.settings, "DATABASE_URL", url)

    assert db_session._get_alembic_config().get_main_option("sqlalchemy.url") == url
