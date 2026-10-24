"""Ambiente do Alembic: usa o mesmo engine e os mesmos models da aplicação."""
import os

from alembic import context
from sqlalchemy import create_engine

from app import database, models  # noqa: F401  (importar models registra as tabelas no metadata)

target_metadata = database.Base.metadata


def _configurar(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,  # permite ALTER TABLE também no SQLite (testes)
        **kwargs,
    )


def rodar_offline():
    _configurar(url=os.getenv("ALEMBIC_DB_URL") or database.DATABASE_URL, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def rodar_online():
    # ALEMBIC_DB_URL: banco alternativo (ex.: SQLite vazio para gerar migrações)
    url = os.getenv("ALEMBIC_DB_URL")
    engine = create_engine(url) if url else database.engine
    with engine.connect() as conexao:
        _configurar(connection=conexao)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    rodar_offline()
else:
    rodar_online()
