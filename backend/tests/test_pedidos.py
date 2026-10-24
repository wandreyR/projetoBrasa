"""Criação de pedido: preços do banco, validações, WebSocket da cozinha e privacidade."""
from conftest import item_bebida, item_montada, item_pizza, pedido
from starlette.websockets import WebSocketDisconnect
import pytest


def test_cardapio_vem_do_banco(client):
    pizzas = client.get("/cardapio/pizzas").json()
    bebidas = client.get("/cardapio/bebidas").json()
    assert pizzas[0]["slug"] == "margherita" and len(pizzas) == 10
    assert [b["slug"] for b in bebidas] == ["coca-cola", "guarana", "suco-natural", "agua"]
    montagem = client.get("/cardapio/montagem").json()
    assert [t["codigo"] for t in montagem["tamanhos"]] == ["P", "M", "G"]
    assert montagem["tamanhos"][1]["preco_base"] == 38
    assert {i["slug"] for i in montagem["massas"]} == {"tradicional", "fina", "integral"}


def test_preco_vem_do_banco_e_ignora_o_navegador(client):
    itens = [dict(item_pizza("calabresa", "M", 2), preco_unitario=0.01), dict(item_bebida(), preco_unitario=0.01)]
    r = client.post("/pedidos", json=pedido(itens, entrega="delivery"))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["subtotal"] == 44 * 2 + 6
    assert p["taxa_entrega"] == 6 and p["bairro_nome"] == "Setor Central"
    assert p["total"] == p["subtotal"] + 6
    assert p["itens"][0]["nome"] == "Calabresa"
    assert len(p["codigo_acompanhamento"]) >= 16 and p["pago"] is False


def test_telefone_normalizado_e_cliente_reaproveitado(client, db_sessao):
    from app import models
    client.post("/pedidos", json=pedido([item_bebida()], telefone="(11) 98888-7777"))
    client.post("/pedidos", json=pedido([item_bebida()], telefone="11988887777"))
    s = db_sessao()
    assert s.query(models.Cliente).filter_by(telefone="11988887777").count() == 1
    s.close()


@pytest.mark.parametrize("ajuste, campo", [
    ({"tipo_entrega": "delivery", "endereco_entrega": None, "bairro_id": 1}, "endereço"),
    ({"tipo_entrega": "delivery", "endereco_entrega": "Rua X", "bairro_id": None}, "bairro"),
    ({"itens": []}, "itens"),
    ({"cliente_telefone": "123"}, "telefone"),
    ({"forma_pagamento": "cheque"}, "pagamento"),
])
def test_validacoes_retornam_422(client, ajuste, campo):
    corpo = pedido([item_bebida()])
    corpo.update(ajuste)
    assert client.post("/pedidos", json=corpo).status_code == 422, campo


def test_pizza_inexistente_ou_sem_tamanho(client):
    assert client.post("/pedidos", json=pedido([item_pizza("nao-existe")])).status_code == 422
    assert client.post("/pedidos", json=pedido([item_pizza(tamanho=None)])).status_code == 422
    assert client.post("/pedidos", json=pedido([item_pizza(tamanho="XL")])).status_code == 422


def test_bairro_inativo_ou_inexistente(client):
    corpo = pedido([item_bebida()], entrega="delivery")
    corpo["bairro_id"] = 999
    assert client.post("/pedidos", json=corpo).status_code == 422


def test_cozinha_recebe_pedido_em_tempo_real(client, cozinha):
    token = cozinha["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/cozinha?token={token}") as ws:
        assert ws.receive_json()["evento"] == "conectado"
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        r = client.post("/pedidos", json=pedido([item_montada()], observacoes="sem cebola"))
        ev = ws.receive_json()
        while ev["evento"] != "novo_pedido":
            ev = ws.receive_json()
        assert ev["pedido"]["id"] == r.json()["id"]
        assert ev["pedido"]["observacoes"] == "sem cebola"
        assert ev["pedido"]["forma_pagamento"] == "pix"
        assert "Mussarela" in ev["pedido"]["itens"][0]["detalhes"]


def test_websocket_sem_token_e_recusado(client):
    with pytest.raises(WebSocketDisconnect) as erro:
        with client.websocket_connect("/ws/cozinha") as ws:
            ws.receive_json()
    assert erro.value.code == 4401


def test_pedido_completo_so_para_equipe_e_acompanhamento_pelo_codigo(client, cozinha):
    p = client.post("/pedidos", json=pedido([item_bebida()], entrega="delivery")).json()
    # pelo número (sequencial, fácil de adivinhar) só a equipe vê
    assert client.get(f"/pedidos/{p['id']}").status_code == 401
    assert client.get(f"/pedidos/{p['id']}", headers=cozinha).json()["cliente_telefone"] == "11999990000"
    # o cliente usa o código secreto do link, e não vê telefone nem endereço
    a = client.get(f"/pedidos/acompanhar/{p['codigo_acompanhamento']}")
    assert a.status_code == 200
    corpo = a.json()
    assert corpo["id"] == p["id"] and corpo["status"] == "pendente" and corpo["cliente_primeiro_nome"] == "Cliente"
    assert "cliente_telefone" not in corpo and "endereco_entrega" not in corpo
    assert client.get("/pedidos/acompanhar/codigo-que-nao-existe").status_code == 404
