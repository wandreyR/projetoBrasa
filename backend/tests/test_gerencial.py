"""Área do dono: permissões, despesas, resumo e cardápio editável."""
from conftest import item_pizza, pedido
from app.tempo import hoje_local


def test_permissoes(client, cozinha, dono):
    assert client.get("/gerencial/resumo").status_code == 401
    assert client.get("/gerencial/resumo", headers=cozinha).status_code == 403
    assert client.get("/gerencial/config/pizzas", headers=cozinha).status_code == 403
    assert client.get("/gerencial/resumo", headers=dono).status_code == 200


def test_despesas_e_resultado(client, dono):
    hoje = str(hoje_local())
    client.post("/pedidos", json=pedido([item_pizza("calabresa", "G", 2)]))  # 108
    r = client.post("/gerencial/despesas", headers=dono, json={"descricao": "Farinha", "categoria": "ingredientes", "valor": 50.456, "data": hoje})
    assert r.status_code == 201 and r.json()["valor"] == 50.46
    resumo = client.get("/gerencial/resumo", headers=dono, params={"inicio": hoje, "fim": hoje}).json()
    assert resumo["faturamento"] == 108 and resumo["despesas"] == 50.46 and resumo["lucro"] == 57.54
    assert resumo["top_itens"][0]["nome"] == "Calabresa"
    assert client.delete(f"/gerencial/despesas/{r.json()['id']}", headers=dono).status_code == 204
    assert client.get("/gerencial/resumo", headers=dono, params={"inicio": "2026-09-10", "fim": "2026-09-01"}).status_code == 422


def test_dono_edita_preco_e_desativa_pizza(client, dono):
    pizzas = {p["slug"]: p for p in client.get("/gerencial/config/pizzas", headers=dono).json()}
    marg = pizzas["margherita"]
    r = client.put(f"/gerencial/config/pizzas/{marg['id']}", headers=dono, json={**marg, "preco_g": 55})
    assert r.status_code == 200
    assert client.post("/pedidos", json=pedido([item_pizza("margherita")])).json()["subtotal"] == 55
    client.put(f"/gerencial/config/pizzas/{marg['id']}", headers=dono, json={**marg, "ativo": 0})
    assert "margherita" not in [p["slug"] for p in client.get("/cardapio/pizzas").json()]
    assert client.post("/pedidos", json=pedido([item_pizza("margherita")])).status_code == 422
    client.put(f"/gerencial/config/pizzas/{marg['id']}", headers=dono, json=marg)


def test_dono_cadastra_pizza_e_bebida(client, dono):
    nova = {"slug": "nordestina", "nome": "Nordestina", "categoria": "especiais", "descricao": "Carne de sol e queijo coalho",
            "preco_p": 39, "preco_m": 50, "preco_g": 61}
    assert client.post("/gerencial/config/pizzas", headers=dono, json=nova).status_code == 201
    assert client.post("/gerencial/config/pizzas", headers=dono, json=nova).status_code == 409
    assert client.post("/gerencial/config/pizzas", headers=dono, json={**nova, "slug": "Com Espaço"}).status_code == 422
    assert "nordestina" in [p["slug"] for p in client.get("/cardapio/pizzas").json()]
    bebida = {"slug": "cerveja", "nome": "Cerveja 600ml", "descricao": "Gelada", "preco": 14}
    assert client.post("/gerencial/config/bebidas", headers=dono, json=bebida).status_code == 201


def test_dono_altera_adicional(client, dono):
    ings = {i["slug"]: i for i in client.get("/gerencial/config/ingredientes", headers=dono).json()}
    client.put(f"/gerencial/config/ingredientes/{ings['bacon']['id']}", headers=dono, json={"preco_adicional": 5, "ativo": 1})
    assert [c["preco_adicional"] for c in client.get("/cardapio/montagem").json()["coberturas"] if c["slug"] == "bacon"] == [5]
    # não deixa desativar a última massa
    for slug in ("fina", "integral"):
        client.put(f"/gerencial/config/ingredientes/{ings[slug]['id']}", headers=dono, json={"preco_adicional": 0, "ativo": 0})
    r = client.put(f"/gerencial/config/ingredientes/{ings['tradicional']['id']}", headers=dono, json={"preco_adicional": 0, "ativo": 0})
    assert r.status_code == 422
