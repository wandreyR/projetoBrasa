"""Operação do dia a dia: horário, pausa, entrega, entregador e pagamento."""
from datetime import datetime, time

from conftest import item_bebida, item_pizza, pedido


# ---------------------------------------------------------------------
# Horário de funcionamento
# ---------------------------------------------------------------------

def _horarios(abre, fecha, fechado_dias=()):
    return [{"dia_semana": d, "abre": abre, "fecha": fecha, "fechado": int(d in fechado_dias)} for d in range(7)]


def test_horario_comum_e_que_passa_da_meia_noite(client, dono, db_sessao):
    from app.loja_service import status_loja
    assert client.put("/gerencial/config/horarios", headers=dono, json=_horarios("18:00", "01:00")).status_code == 200
    s = db_sessao()
    # quinta 2026-10-22: 19h aberto; 00:30 de sexta ainda é o expediente de quinta; 14h fechado
    assert status_loja(s, datetime(2026, 10, 22, 19, 0))["aberto"] is True
    assert status_loja(s, datetime(2026, 10, 23, 0, 30))["aberto"] is True
    fechado = status_loja(s, datetime(2026, 10, 22, 14, 0))
    assert fechado["aberto"] is False and "Abrimos hoje às 18:00" in fechado["mensagem"]
    s.close()


def test_dia_fechado_e_pedido_recusado_fora_do_horario(client, dono, db_sessao):
    from app.loja_service import status_loja
    from app.tempo import agora_local
    hoje = agora_local().weekday()
    client.put("/gerencial/config/horarios", headers=dono, json=_horarios("00:00", "23:59", fechado_dias=(hoje,)))
    r = client.post("/pedidos", json=pedido([item_bebida()]))
    assert r.status_code == 409 and "fechados" in r.json()["detail"]
    s = db_sessao()
    assert "amanhã" in status_loja(s)["mensagem"] or "às" in status_loja(s)["mensagem"]
    s.close()
    client.put("/gerencial/config/horarios", headers=dono, json=_horarios("00:00", "23:59"))
    assert client.post("/pedidos", json=pedido([item_bebida()])).status_code == 201


def test_horarios_invalidos(client, dono):
    assert client.put("/gerencial/config/horarios", headers=dono, json=_horarios("18:00", "01:00")[:5]).status_code == 422
    assert client.put("/gerencial/config/horarios", headers=dono, json=_horarios("18:00", "18:00")).status_code == 422


def test_cozinha_pausa_pedidos(client, cozinha):
    r = client.put("/cozinha/pausa", headers=cozinha, json={"pausado": True})
    assert r.json()["aberto"] is False and client.get("/cardapio/loja").json()["pausado"] is True
    assert client.post("/pedidos", json=pedido([item_bebida()])).status_code == 409
    client.put("/cozinha/pausa", headers=cozinha, json={"pausado": False})
    assert client.post("/pedidos", json=pedido([item_bebida()])).status_code == 201
    assert client.put("/cozinha/pausa", json={"pausado": True}).status_code == 401


# ---------------------------------------------------------------------
# Entrega
# ---------------------------------------------------------------------

def test_taxa_por_bairro(client, dono):
    novo = client.post("/gerencial/config/bairros", headers=dono, json={"nome": "Setor Pedro Ludovico", "taxa": 9.5}).json()
    assert client.post("/gerencial/config/bairros", headers=dono, json={"nome": "Setor Pedro Ludovico", "taxa": 1}).status_code == 409
    p = client.post("/pedidos", json=pedido([item_bebida()], entrega="delivery", bairro_id=novo["id"])).json()
    assert p["taxa_entrega"] == 9.5 and p["bairro_nome"] == "Setor Pedro Ludovico"
    client.put(f"/gerencial/config/bairros/{novo['id']}", headers=dono, json={"nome": "Setor Pedro Ludovico", "taxa": 9.5, "ativo": 0})
    assert novo["id"] not in [b["id"] for b in client.get("/cardapio/bairros").json()]
    assert client.post("/pedidos", json=pedido([item_bebida()], entrega="delivery", bairro_id=novo["id"])).status_code == 422


def test_fluxo_de_entrega_com_entregador(client, cozinha, dono):
    ent = client.post("/gerencial/config/entregadores", headers=dono, json={"nome": "Carlos Moto", "telefone": "62999990000"}).json()
    assert [e["nome"] for e in client.get("/cozinha/entregadores", headers=cozinha).json()] == ["Carlos Moto"]
    p = client.post("/pedidos", json=pedido([item_pizza()], entrega="delivery")).json()
    for st in ("em_preparo", "pronto"):
        client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": st})
    r = client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha,
                     json={"status": "saiu_entrega", "entregador_id": ent["id"]}).json()
    assert r["status"] == "saiu_entrega" and r["entregador_nome"] == "Carlos Moto" and r["saiu_entrega_em"]
    acompanhamento = client.get(f"/pedidos/acompanhar/{p['codigo_acompanhamento']}").json()
    assert acompanhamento["status"] == "saiu_entrega" and acompanhamento["entregador_nome"] == "Carlos"
    r = client.patch(f"/cozinha/pedidos/{p['id']}/status", headers=cozinha, json={"status": "entregue"}).json()
    assert r["finalizado_em"]
    # retirada não "sai para entrega"
    p2 = client.post("/pedidos", json=pedido([item_bebida()])).json()
    assert client.patch(f"/cozinha/pedidos/{p2['id']}/status", headers=cozinha, json={"status": "saiu_entrega"}).status_code == 422


# ---------------------------------------------------------------------
# Pagamento
# ---------------------------------------------------------------------

def test_pagamento_em_dinheiro_com_troco(client):
    p = client.post("/pedidos", json=pedido([item_bebida()], pagamento="dinheiro", troco_para=50)).json()
    assert p["forma_pagamento"] == "dinheiro" and p["troco_para"] == 50
    r = client.post("/pedidos", json=pedido([item_pizza()], pagamento="dinheiro", troco_para=20))
    assert r.status_code == 422 and "troco" in r.json()["detail"]
    # troco só faz sentido em dinheiro
    assert client.post("/pedidos", json=pedido([item_bebida()], pagamento="pix", troco_para=50)).json()["troco_para"] is None


def test_marcar_como_pago_e_resumo(client, cozinha, dono):
    p = client.post("/pedidos", json=pedido([item_bebida()], pagamento="credito")).json()
    r = client.patch(f"/cozinha/pedidos/{p['id']}/pagamento", headers=cozinha, json={"pago": True}).json()
    assert r["pago"] is True
    resumo = client.get("/gerencial/resumo", headers=dono).json()
    formas = {x["forma"]: x for x in resumo["por_pagamento"]}
    assert formas["credito"]["pedidos"] >= 1 and "pix" in formas
    assert resumo["a_receber"] > 0  # os pix de teste não foram marcados como pagos
    assert resumo["por_entregador"][0]["nome"] == "Carlos Moto" and resumo["por_entregador"][0]["entregas"] == 1
