"""Área do entregador: acesso, aviso de pedido pronto, pegar, entregar e devolver."""
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import item_bebida, item_pizza, pedido


def _cadastrar(client, dono, nome, telefone, senha="1234"):
    r = client.post("/gerencial/config/entregadores", headers=dono, json={"nome": nome, "telefone": telefone, "senha": senha})
    assert r.status_code == 201, r.text
    return r.json()


def _entrar(client, telefone, senha="1234"):
    r = client.post("/auth/entregador/login", json={"telefone": telefone, "senha": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def entregadores(client, dono):
    joao = _cadastrar(client, dono, "João Moto", "(62) 98111-1111")
    maria = _cadastrar(client, dono, "Maria Bike", "(62) 98222-2222")
    return {"joao": joao, "maria": maria,
            "h_joao": _entrar(client, "62981111111"), "h_maria": _entrar(client, "+55 (62) 98222-2222")}


def _pedido_pronto(client, cozinha, entrega="delivery"):
    p = client.post("/pedidos", json=pedido([item_pizza(), item_bebida()], entrega=entrega, pagamento="dinheiro", troco_para=100)).json()
    for st in ("em_preparo", "pronto"):
        assert client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": st}).status_code == 200
    return p


def test_cadastro_de_acesso(client, dono, entregadores):
    assert entregadores["joao"]["tem_acesso"] is True and "senha" not in entregadores["joao"]
    assert client.post("/gerencial/config/entregadores", headers=dono,
                       json={"nome": "Sem celular", "senha": "1234"}).status_code == 422
    assert client.post("/gerencial/config/entregadores", headers=dono,
                       json={"nome": "Repetido", "telefone": "62981111111", "senha": "1234"}).status_code == 409
    assert client.post("/gerencial/config/entregadores", headers=dono,
                       json={"nome": "Curta", "telefone": "62983333333", "senha": "12"}).status_code == 422
    # sem senha: entregador só para a cozinha escolher, sem acesso
    sem = client.post("/gerencial/config/entregadores", headers=dono, json={"nome": "Só cadastro", "telefone": "62984444444"}).json()
    assert sem["tem_acesso"] is False


def test_login(client, entregadores):
    assert client.post("/auth/entregador/login", json={"telefone": "62981111111", "senha": "errada"}).status_code == 401
    assert client.post("/auth/entregador/login", json={"telefone": "62984444444", "senha": "1234"}).status_code == 401


def test_entregador_nao_acessa_a_equipe(client, entregadores, cozinha):
    h = entregadores["h_joao"]
    for rota in ("/cozinha/pedidos", "/estoque/itens", "/gerencial/resumo", "/auth/me"):
        assert client.get(rota, headers=h).status_code == 401, rota
    # e a equipe não entra na área do entregador com o token dela
    assert client.get("/entregador/painel", headers=cozinha).status_code == 401
    assert client.get("/entregador/painel").status_code == 401


def test_aviso_quando_fica_pronto(client, cozinha, entregadores):
    token = entregadores["h_joao"]["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/entregador?token={token}") as ws:
        assert ws.receive_json()["evento"] == "conectado"
        p = client.post("/pedidos", json=pedido([item_pizza()], entrega="delivery")).json()
        assert ws.receive_json() == {"evento": "atualizar"}  # novo pedido de entrega na cozinha
        client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "em_preparo"})
        ws.receive_json()
        client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "pronto"})
        ev = ws.receive_json()
        assert ev == {"evento": "pedido_pronto", "pedido": {"id": p["id"], "bairro_nome": "Setor Central"}}
    # pedido de retirada não avisa entregador
    with client.websocket_connect(f"/ws/entregador?token={token}") as ws:
        ws.receive_json()
        r = client.post("/pedidos", json=pedido([item_bebida()], entrega="retirada")).json()
        client.patch(f"/cozinha/pedidos/{r['id']}/status", headers=cozinha, json={"status": "pronto"})
        ws.send_text("ping")
        assert ws.receive_text() == "pong"  # nenhum evento chegou antes do pong


def test_websocket_exige_acesso_de_entregador(client, cozinha):
    with pytest.raises(WebSocketDisconnect) as erro:
        with client.websocket_connect(f"/ws/entregador?token={cozinha['Authorization'].split()[1]}") as ws:
            ws.receive_json()
    assert erro.value.code == 4401


def test_fluxo_completo_da_entrega(client, cozinha, entregadores):
    p = _pedido_pronto(client, cozinha)
    painel = client.get("/entregador/painel", headers=entregadores["h_joao"]).json()
    pronto = next(x for x in painel["prontos"] if x["id"] == p["id"])
    assert pronto["endereco_entrega"] == "Rua Teste, 10" and pronto["cliente_telefone"] == "11999990000"
    assert pronto["forma_pagamento"] == "dinheiro" and pronto["troco_para"] == 100

    # João pega; Maria chega atrasada
    r = client.post(f"/entregador/pedidos/{p['id']}/sair", headers=entregadores["h_joao"])
    assert r.status_code == 200 and r.json()["status"] == "saiu_entrega" and r.json()["minha"] is True
    assert client.post(f"/entregador/pedidos/{p['id']}/sair", headers=entregadores["h_maria"]).status_code == 409
    assert client.post(f"/entregador/pedidos/{p['id']}/sair", headers=entregadores["h_joao"]).status_code == 200  # toque repetido
    assert p["id"] not in [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_maria"]).json()["prontos"]]
    assert [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_joao"]).json()["minhas"]] == [p["id"]]

    # a cozinha vê quem levou
    fila = {x["id"]: x for x in client.get("/cozinha/pedidos", headers=cozinha).json()}
    assert fila[p["id"]]["entregador_nome"] == "João Moto"

    # só quem levou dá baixa
    assert client.post(f"/entregador/pedidos/{p['id']}/entregue", headers=entregadores["h_maria"], json={}).status_code == 409
    r = client.post(f"/entregador/pedidos/{p['id']}/entregue", headers=entregadores["h_joao"], json={"recebi_pagamento": True}).json()
    assert r["status"] == "entregue" and r["pago"] is True
    painel = client.get("/entregador/painel", headers=entregadores["h_joao"]).json()
    assert painel["entregues_hoje"] == 1 and painel["taxas_hoje"] == 6 and painel["minhas"] == []


def test_nao_consegui_entregar(client, cozinha, entregadores):
    p = _pedido_pronto(client, cozinha)
    client.post(f"/entregador/pedidos/{p['id']}/sair", headers=entregadores["h_maria"])
    r = client.post(f"/entregador/pedidos/{p['id']}/devolver", headers=entregadores["h_maria"]).json()
    assert r["status"] == "pronto"
    assert p["id"] in [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_joao"]).json()["prontos"]]


def test_regras(client, cozinha, entregadores, dono):
    # não pega pedido que ainda está no forno, nem de retirada
    p = client.post("/pedidos", json=pedido([item_pizza()], entrega="delivery")).json()
    assert client.post(f"/entregador/pedidos/{p['id']}/sair", headers=entregadores["h_joao"]).status_code == 409
    assert p["id"] in [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_joao"]).json()["na_cozinha"]]
    r = _pedido_pronto(client, cozinha, entrega="retirada")
    assert client.post(f"/entregador/pedidos/{r['id']}/sair", headers=entregadores["h_joao"]).status_code == 404
    # pronto designado pela cozinha para a Maria não aparece para o João
    d = _pedido_pronto(client, cozinha)
    client.patch(f"/cozinha/pedidos/{d['id']}/status", headers=cozinha,
                 json={"status": "saiu_entrega", "entregador_id": entregadores["maria"]["id"]})
    assert d["id"] in [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_maria"]).json()["minhas"]]
    assert d["id"] not in [x["id"] for x in client.get("/entregador/painel", headers=entregadores["h_joao"]).json()["minhas"]]
    # dono remove o acesso: o token deixa de valer na hora
    m = entregadores["maria"]
    client.put(f"/gerencial/config/entregadores/{m['id']}", headers=dono,
               json={"nome": m["nome"], "telefone": m["telefone"], "remover_acesso": True})
    assert client.get("/entregador/painel", headers=entregadores["h_maria"]).status_code == 401
