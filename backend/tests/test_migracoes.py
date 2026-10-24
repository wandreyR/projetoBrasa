"""Migrações do Alembic: sobem, descem e adotam um banco criado antes do Alembic."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app import database
from app.migracoes import migrar_banco

BACKEND = Path(__file__).resolve().parent.parent


def _cfg():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def _usar_banco(tmp_path, nome):
    engine = create_engine(f"sqlite:///{tmp_path / nome}")
    database.engine = engine
    return engine


def test_sobe_desce_e_sobe(tmp_path):
    engine = _usar_banco(tmp_path, "a.db")
    cfg = _cfg()
    command.upgrade(cfg, "head")
    assert "tamanhos_pizza" in inspect(engine).get_table_names()
    command.downgrade(cfg, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(cfg, "head")
    colunas = {c["name"] for c in inspect(engine).get_columns("pedidos")}
    assert {"forma_pagamento", "codigo_acompanhamento", "entregador_id"} <= colunas


def test_adota_banco_antigo_e_preenche_dados(tmp_path):
    engine = _usar_banco(tmp_path, "b.db")
    cfg = _cfg()
    # simula o banco de produção de antes: esquema 0001 sem a tabela de controle do Alembic
    command.upgrade(cfg, "0001")
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text("INSERT INTO bebidas (nome, descricao, preco, ativo) VALUES ('Guaraná 350ml', '', 6, 1)"))
        c.execute(text("INSERT INTO clientes (nome, telefone) VALUES ('Ana', '11900000000')"))
        c.execute(text("INSERT INTO pedidos (cliente_id, tipo_entrega, status, subtotal, taxa_entrega, total) "
                       "VALUES (1, 'retirada', 'pendente', 10, 0, 10)"))
    migrar_banco()
    with engine.connect() as c:
        ultima = ScriptDirectory.from_config(cfg).get_current_head()
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == ultima
        assert c.execute(text("SELECT slug FROM bebidas")).scalar() == "guarana"
        codigo, pago = c.execute(text("SELECT codigo_acompanhamento, pago FROM pedidos")).one()
        assert len(codigo) >= 16 and pago == 1  # pedidos antigos contam como pagos


def test_dia_da_semana_nao_e_autoincremento():
    """No MySQL uma chave inteira vira AUTO_INCREMENT e o dia 0 (segunda) seria trocado."""
    from app import models
    assert models.HorarioFuncionamento.__table__.c.dia_semana.autoincrement is False


def test_0003_conserta_dias_gravados_errado(tmp_path):
    engine = _usar_banco(tmp_path, "c.db")
    cfg = _cfg()
    command.upgrade(cfg, "0002")
    with engine.begin() as c:  # o que o defeito gravou no MySQL: dias 1..6 e 8
        for d in (1, 2, 3, 4, 5, 6, 8):
            c.execute(text("INSERT INTO horarios_funcionamento (dia_semana, abre, fecha, fechado) VALUES (:d, '00:00:00', '23:59:00', 0)"), {"d": d})
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert sorted(d for (d,) in c.execute(text("SELECT dia_semana FROM horarios_funcionamento"))) == list(range(7))
