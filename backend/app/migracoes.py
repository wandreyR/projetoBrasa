"""Aplica as migrações do Alembic na inicialização (substitui o antigo create_all)."""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from . import database

logger = logging.getLogger("brasa.migracoes")
PASTA_BACKEND = Path(__file__).resolve().parent.parent
REVISAO_INICIAL = "0001"  # esquema que o create_all gerava antes do Alembic


def migrar_banco():
    cfg = Config(str(PASTA_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(PASTA_BACKEND / "migrations"))

    tabelas = inspect(database.engine).get_table_names()
    if "alembic_version" not in tabelas and "pedidos" in tabelas:
        # banco criado antes do Alembic: já está no esquema inicial, só registra isso
        logger.info("Banco existente sem controle de versão: marcando como %s", REVISAO_INICIAL)
        command.stamp(cfg, REVISAO_INICIAL)
    command.upgrade(cfg, "head")
