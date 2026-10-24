"""Pix: BR Code, chave configurável pelo dono e comprovante enviado pelo cliente."""
import pytest

from conftest import item_bebida, item_pizza, pedido
from app.pix_service import ChavePixInvalida, copia_e_cola, normalizar_chave

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture(autouse=True)
def pasta_temporaria(tmp_path, monkeypatch):
    from app.routers import pedidos
    monkeypatch.setattr(pedidos, "PASTA_COMPROVANTES", tmp_path)
    return tmp_path


def test_br_code_igual_ao_exemplo_do_banco_central():
    esperado = ("00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
                "5913Fulano de Tal6008BRASILIA62070503***63041D3D")
    assert copia_e_cola("123e4567-e12b-12d1-a456-426655440000", "Fulano de Tal", "BRASILIA") == esperado


@pytest.mark.parametrize("tipo, chave, esperado", [
    ("telefone", "(62) 99999-0000", "+5562999990000"),
    ("telefone", "+55 62 99999-0000", "+5562999990000"),
    ("cpf", "123.456.789-09", "12345678909"),
    ("cnpj", "12.345.678/0001-95", "12345678000195"),
    ("email", "Pix@Brasa.com", "pix@brasa.com"),
])
def test_chave_normalizada(tipo, chave, esperado):
    assert normalizar_chave(tipo, chave) == esperado


def test_chave_invalida():
    with pytest.raises(ChavePixInvalida):
        normalizar_chave("cpf", "123")


def test_dono_configura_e_cliente_ve_a_chave(client, dono, cozinha):
    assert client.get("/gerencial/config/pix", headers=cozinha).status_code == 403
    publico = client.get("/cardapio/pix").json()
    assert publico == {"disponivel": True, "chave": "+5562999990000", "nome": "Brasa Pizzaria"}
    r = client.put("/gerencial/config/pix", headers=dono, json={"tipo": "cpf", "chave": "123", "nome": "X", "cidade": "Y"})
    assert r.status_code == 422


def test_pix_desligado_recusa_pedido_pix(client, dono):
    client.put("/gerencial/config/pix", headers=dono, json={"tipo": "telefone", "chave": "", "nome": "", "cidade": ""})
    assert client.get("/cardapio/pix").json()["disponivel"] is False
    assert client.post("/pedidos", json=pedido([item_bebida()], pagamento="pix")).status_code == 422
    assert client.post("/pedidos", json=pedido([item_bebida()], pagamento="credito")).status_code == 201
    client.put("/gerencial/config/pix", headers=dono,
               json={"tipo": "telefone", "chave": "(62) 99999-0000", "nome": "Brasa Pizzaria", "cidade": "Goiânia"})


def test_qr_code_com_valor_do_pedido(client):
    p = client.post("/pedidos", json=pedido([item_pizza("calabresa", "G")], pagamento="pix")).json()
    pix = client.get(f"/pedidos/acompanhar/{p['codigo_acompanhamento']}/pix").json()
    assert pix["valor"] == 54 and pix["chave"] == "+5562999990000"
    assert "540554.00" in pix["copia_e_cola"]                     # campo 54 = valor
    assert f"BRASA{p['id']}" in pix["copia_e_cola"]               # identificador do pedido
    assert "Goiania" in pix["copia_e_cola"]                       # sem acento (exigência do padrão)
    assert pix["qr_svg"].lstrip().startswith("<?xml") and "<svg" in pix["qr_svg"]
    outro = client.post("/pedidos", json=pedido([item_bebida()], pagamento="dinheiro")).json()
    assert client.get(f"/pedidos/acompanhar/{outro['codigo_acompanhamento']}/pix").status_code == 409


def test_envio_do_comprovante_avisa_a_cozinha(client, cozinha, pasta_temporaria):
    token = cozinha["Authorization"].split()[1]
    p = client.post("/pedidos", json=pedido([item_bebida()], pagamento="pix")).json()
    codigo = p["codigo_acompanhamento"]
    with client.websocket_connect(f"/ws/cozinha?token={token}") as ws:
        ws.receive_json()
        r = client.post(f"/pedidos/acompanhar/{codigo}/comprovante", files={"arquivo": ("comp.png", PNG, "image/png")})
        assert r.status_code == 201
        ev = ws.receive_json()
        while ev["evento"] != "comprovante_recebido":
            ev = ws.receive_json()
        assert ev["pedido"]["id"] == p["id"] and ev["pedido"]["comprovante_enviado_em"]
    assert client.get(f"/pedidos/acompanhar/{codigo}").json()["comprovante_enviado"] is True
    assert len(list(pasta_temporaria.iterdir())) == 1

    # só a equipe baixa o comprovante
    assert client.get(f"/cozinha/pedidos/{p['id']}/comprovante").status_code == 401
    baixado = client.get(f"/cozinha/pedidos/{p['id']}/comprovante", headers=cozinha)
    assert baixado.status_code == 200 and baixado.content == PNG and baixado.headers["content-type"] == "image/png"

    # reenviar substitui o arquivo anterior (não acumula)
    assert client.post(f"/pedidos/acompanhar/{codigo}/comprovante", files={"arquivo": ("c.pdf", PDF, "application/pdf")}).status_code == 201
    assert [f.suffix for f in pasta_temporaria.iterdir()] == [".pdf"]

    # depois de marcado como pago, não aceita mais
    client.patch(f"/cozinha/pedidos/{p['id']}/pagamento", headers=cozinha, json={"pago": True})
    assert client.post(f"/pedidos/acompanhar/{codigo}/comprovante", files={"arquivo": ("c.png", PNG, "image/png")}).status_code == 409


def test_comprovante_invalido(client):
    codigo = client.post("/pedidos", json=pedido([item_bebida()], pagamento="pix")).json()["codigo_acompanhamento"]
    # extensão de imagem, mas o conteúdo é texto: recusado pelo conteúdo real
    r = client.post(f"/pedidos/acompanhar/{codigo}/comprovante", files={"arquivo": ("falso.png", b"isto nao e imagem", "image/png")})
    assert r.status_code == 415
    grande = PNG + b"0" * (5 * 1024 * 1024)
    assert client.post(f"/pedidos/acompanhar/{codigo}/comprovante", files={"arquivo": ("g.png", grande, "image/png")}).status_code == 413
    nao_pix = client.post("/pedidos", json=pedido([item_bebida()], pagamento="debito")).json()["codigo_acompanhamento"]
    assert client.post(f"/pedidos/acompanhar/{nao_pix}/comprovante", files={"arquivo": ("c.png", PNG, "image/png")}).status_code == 409
    assert client.post("/pedidos/acompanhar/codigo-inexistente-123/comprovante", files={"arquivo": ("c.png", PNG, "image/png")}).status_code == 404
