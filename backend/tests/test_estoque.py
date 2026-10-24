"""Estoque: alertas, baixa automática, estorno e venda bloqueada sem saldo."""
from conftest import item_bebida, item_montada, item_pizza, pedido, saldo


def _item_id(client, h, nome):
    return {i["nome"]: i["id"] for i in client.get("/estoque/itens", headers=h).json()}[nome]


def _ajustar(client, h, nome, qtd):
    r = client.post(f"/estoque/itens/{_item_id(client, h, nome)}/movimentar", headers=h, json={"tipo": "ajuste", "quantidade": qtd})
    assert r.status_code == 200, r.text
    return r.json()


def test_estoque_exige_login_e_tem_minimo_padrao(client, cozinha):
    assert client.get("/estoque/itens").status_code == 401
    itens = {i["nome"]: i for i in client.get("/estoque/itens", headers=cozinha).json()}
    assert itens["Farinha de trigo"]["minimo"] == 10 and itens["Caixa de pizza"]["minimo"] == 10
    assert itens["Coca-Cola 350ml (lata)"]["bebida_nome"] == "Coca-Cola 350ml"


def test_baixa_automatica_e_estorno(client, cozinha):
    _ajustar(client, cozinha, "Coca-Cola 350ml (lata)", 48)
    _ajustar(client, cozinha, "Bacon", 12)
    _ajustar(client, cozinha, "Farinha de trigo", 50)
    itens = [item_bebida(quantidade=2), item_pizza(),
             item_montada("G", ["Tradicional", "Molho de tomate", "Bacon", "Bacon"], quantidade=2)]
    p = client.post("/pedidos", json=pedido(itens)).json()
    assert saldo(client, cozinha, "Coca-Cola 350ml (lata)") == 46
    assert saldo(client, cozinha, "Farinha de trigo") == 49.3           # 0,35 × 2 pizzas
    assert saldo(client, cozinha, "Bacon") == 11.52                     # 0,12 × 2 porções × 2 pizzas
    assert saldo(client, cozinha, "Calabresa") == 15                    # pizza do cardápio: baixa manual

    client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "cancelado"})
    assert saldo(client, cozinha, "Coca-Cola 350ml (lata)") == 48 and saldo(client, cozinha, "Bacon") == 12
    client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "pendente"})
    assert saldo(client, cozinha, "Coca-Cola 350ml (lata)") == 46
    client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "cancelado"})
    assert saldo(client, cozinha, "Coca-Cola 350ml (lata)") == 48


def test_alerta_abaixo_do_minimo(client, cozinha):
    r = _ajustar(client, cozinha, "Farinha de trigo", 9.5)
    assert r["status"] == "baixo"
    assert "Farinha de trigo" in [a["nome"] for a in client.get("/estoque/alertas", headers=cozinha).json()]
    _ajustar(client, cozinha, "Farinha de trigo", 50)


def test_venda_sem_estoque_e_proibida(client, cozinha, db_sessao):
    from app import models
    _ajustar(client, cozinha, "Coca-Cola 350ml (lata)", 2)
    s = db_sessao(); antes = s.query(models.Pedido).count(); s.close()
    r = client.post("/pedidos", json=pedido([item_bebida(quantidade=3)]))
    assert r.status_code == 409 and "restam 2 un" in r.json()["detail"]
    s = db_sessao(); assert s.query(models.Pedido).count() == antes; s.close()

    assert client.post("/pedidos", json=pedido([item_bebida(quantidade=2)])).status_code == 201
    assert client.get("/cardapio/disponibilidade").json()["bebidas_esgotadas"] == ["Coca-Cola 350ml"]
    r = client.post("/pedidos", json=pedido([item_bebida()]))
    assert r.status_code == 409 and "esgotado" in r.json()["detail"]
    _ajustar(client, cozinha, "Coca-Cola 350ml (lata)", 48)


def test_pizza_montada_respeita_saldo_por_tamanho(client, cozinha):
    _ajustar(client, cozinha, "Bacon", 0.1)
    esgotados = client.get("/cardapio/disponibilidade").json()["ingredientes_esgotados"]
    assert "Bacon" not in esgotados["P"] and "Bacon" in esgotados["G"]
    assert client.post("/pedidos", json=pedido([item_montada("G", ["Tradicional", "Molho de tomate", "Bacon"])])).status_code == 409
    assert client.post("/pedidos", json=pedido([item_montada("P", ["Tradicional", "Molho de tomate", "Bacon", "Bacon"])])).status_code == 409
    assert client.post("/pedidos", json=pedido([item_montada("P", ["Tradicional", "Molho de tomate", "Bacon"])])).status_code == 201
    _ajustar(client, cozinha, "Bacon", 12)


def test_saida_manual_maior_que_saldo(client, cozinha):
    item = _item_id(client, cozinha, "Palmito")
    r = client.post(f"/estoque/itens/{item}/movimentar", headers=cozinha, json={"tipo": "saida", "quantidade": 999})
    assert r.status_code == 422


def test_cadastro_e_exclusao_de_item(client, cozinha, dono):
    r = client.post("/estoque/itens", headers=cozinha, json={"nome": "Orégano", "unidade": "kg", "quantidade": 2})
    assert r.status_code == 201 and r.json()["status"] == "baixo"
    assert client.post("/estoque/itens", headers=cozinha, json={"nome": "orégano", "unidade": "kg"}).status_code == 409
    assert client.delete(f"/estoque/itens/{r.json()['id']}", headers=cozinha).status_code == 403
    assert client.delete(f"/estoque/itens/{r.json()['id']}", headers=dono).status_code == 204
