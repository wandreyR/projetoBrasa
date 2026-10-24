"""Pizza montada: preço calculado no servidor a partir do banco."""
from conftest import item_montada, pedido


def _preco(client, **kw):
    r = client.post("/pedidos", json=pedido([item_montada(**kw)]))
    assert r.status_code == 201, r.text
    return r.json()["itens"][0]


def test_preco_calculado_no_servidor(client):
    # M (38) + Tradicional (0) + Molho de tomate (0) + Mussarela (3)
    item = _preco(client, tamanho="M")
    assert item["preco_unitario"] == 41
    assert item["detalhes"] == "Tradicional · Molho de tomate · Mussarela"


def test_preco_do_navegador_e_ignorado(client):
    assert _preco(client, tamanho="G", preco=0.01)["preco_unitario"] == 48 + 3


def test_adicionais_pagos_e_porcoes_repetidas(client):
    # G (48) + Integral (2) + Barbecue (2) + Bacon 2× (4+4) + Catupiry (4)
    item = _preco(client, tamanho="G", ingredientes=["Integral", "Barbecue", "Bacon", "bacon", "Catupiry"])
    assert item["preco_unitario"] == 48 + 2 + 2 + 8 + 4
    assert item["detalhes"] == "Integral · Barbecue · Bacon (2×), Catupiry"


def test_aceita_slug_dos_ingredientes(client):
    assert _preco(client, tamanho="P", ingredientes=["fina", "branco", "rucula"])["preco_unitario"] == 28 + 3


def test_sem_adicionais(client):
    item = _preco(client, tamanho="P", ingredientes=["Tradicional", "Molho de tomate"])
    assert item["preco_unitario"] == 28 and item["detalhes"].endswith("sem ingredientes extras")


def test_regras_de_montagem(client):
    casos = [
        ["Tradicional", "Molho de tomate", "Bacon", "Bacon", "Bacon", "Bacon"],  # 4 porções
        ["Molho de tomate", "Mussarela"],                                        # sem massa
        ["Tradicional", "Fina", "Molho de tomate"],                              # duas massas
        ["Tradicional", "Molho de tomate", "Abacaxi"],                           # não existe
        [],                                                                      # vazio
    ]
    for ingredientes in casos:
        r = client.post("/pedidos", json=pedido([item_montada(ingredientes=ingredientes)]))
        assert r.status_code == 422, ingredientes


def test_preco_muda_quando_o_dono_altera_no_banco(client, dono):
    assert client.put("/gerencial/config/tamanhos/M", headers=dono, json={"fatias": 6, "preco_base": 40}).status_code == 200
    assert _preco(client, tamanho="M")["preco_unitario"] == 43
    client.put("/gerencial/config/tamanhos/M", headers=dono, json={"fatias": 6, "preco_base": 38})
