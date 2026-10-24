"""Configuração dos testes: cada arquivo de teste roda com um banco SQLite em memória
novo, criado pelas mesmas migrações do Alembic usadas em produção.

Rodar (dentro de backend/):   python -m pytest
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import database  # noqa: E402


def _banco_novo():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessao = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # o app guarda referências ao engine/sessão em alguns módulos: troca em todos
    from app import main
    from app.routers import pedidos
    database.engine, database.SessionLocal = engine, sessao
    main.engine, main.SessionLocal = engine, sessao
    pedidos.SessionLocal = sessao
    return sessao


@pytest.fixture(scope="module")
def client():
    _banco_novo()
    from app.main import app
    with TestClient(app) as c:
        # como numa instalação real: o dono já cadastrou a chave Pix (os pedidos de teste usam Pix)
        r = c.put("/gerencial/config/pix", headers=_login(c, "dono@brasa.com"),
                  json={"tipo": "telefone", "chave": "(62) 99999-0000", "nome": "Brasa Pizzaria", "cidade": "Goiânia"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture(scope="module")
def db_sessao(client):
    return database.SessionLocal


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "senha": "brasa123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def cozinha(client):
    return _login(client, "cozinha@brasa.com")


@pytest.fixture(scope="module")
def dono(client):
    return _login(client, "dono@brasa.com")


# ---------------------------------------------------------------------
# Atalhos para montar pedidos
# ---------------------------------------------------------------------

def item_pizza(slug="calabresa", tamanho="G", quantidade=1):
    return {"tipo": "cardapio", "ref": slug, "nome": slug, "tamanho": tamanho, "quantidade": quantidade}


def item_bebida(slug="coca-cola", quantidade=1):
    return {"tipo": "bebida", "ref": slug, "nome": slug, "quantidade": quantidade}


def item_montada(tamanho="M", ingredientes=("Tradicional", "Molho de tomate", "Mussarela"), quantidade=1, preco=None):
    item = {"tipo": "custom", "nome": "Pizza montada", "tamanho": tamanho, "quantidade": quantidade,
            "ingredientes": list(ingredientes)}
    if preco is not None:
        item["preco_unitario"] = preco
    return item


def pedido(itens, entrega="retirada", pagamento="pix", telefone="11999990000", **extra):
    corpo = {"cliente_nome": "Cliente Teste", "cliente_telefone": telefone, "tipo_entrega": entrega,
             "forma_pagamento": pagamento, "itens": itens}
    if entrega == "delivery":
        corpo.update(endereco_entrega="Rua Teste, 10", bairro_id=1)
    corpo.update(extra)
    return corpo


def saldo(client, headers, nome):
    return {i["nome"]: i["quantidade"] for i in client.get("/estoque/itens", headers=headers).json()}[nome]
