import os
import re
import secrets
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..database import get_db, SessionLocal
from ..auth import get_current_user, usuario_do_token
from ..estoque_service import (
    EstoqueInsuficiente, ajustar_por_mudanca_de_status, baixar_pedido, consumo_do_pedido, evento_estoque,
)
from ..loja_service import definir_pausa, status_loja
from ..pix_service import pix_disponivel, pix_do_pedido
from ..tempo import hoje_local, inicio_do_dia_em_utc
from ..websocket_manager import avisar_entregadores, manager
from .cardapio import MAX_PORCOES

router = APIRouter(tags=["Pedidos"])

# Código de fechamento do WebSocket quando o token é inválido/ausente.
# Faixa 4000-4999 é livre para uso da aplicação; o front usa esse código
# para saber que precisa pedir login de novo (em vez de ficar reconectando).
WS_CODIGO_NAO_AUTORIZADO = 4401

STATUS_EM_ANDAMENTO = [
    models.StatusPedido.pendente,
    models.StatusPedido.em_preparo,
    models.StatusPedido.pronto,
    models.StatusPedido.saiu_entrega,
]
STATUS_FINAIS = (models.StatusPedido.entregue, models.StatusPedido.cancelado)

# Comprovantes do Pix: pasta fora do código (volume do Docker), tamanho e tipos limitados
PASTA_COMPROVANTES = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[2] / "uploads")))
LIMITE_COMPROVANTE = 5 * 1024 * 1024  # 5 MB
TIPOS_COMPROVANTE = {  # assinatura dos primeiros bytes → (extensão, tipo)
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"%PDF-": ("pdf", "application/pdf"),
}
NOME_ARQUIVO = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}


def _tipo_do_arquivo(conteudo: bytes) -> Optional[str]:
    """Confere o conteúdo real (não confia na extensão nem no tipo enviado pelo navegador)."""
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "webp"
    for assinatura, (extensao, _) in TIPOS_COMPROVANTE.items():
        if conteudo.startswith(assinatura):
            return extensao
    return None


def _iso(momento: Optional[datetime]) -> Optional[str]:
    return momento.isoformat() if momento else None


def _serializar_pedido(pedido: models.Pedido) -> dict:
    """Monta o dicionário enviado via WebSocket para a cozinha.

    Tem tudo que o card do Kanban precisa para ser desenhado sem
    uma segunda chamada à API.
    """
    return {
        "id": pedido.id,
        "status": pedido.status.value,
        "tipo_entrega": pedido.tipo_entrega.value,
        "endereco_entrega": pedido.endereco_entrega,
        "bairro_nome": pedido.bairro_nome,
        "observacoes": pedido.observacoes,
        "subtotal": pedido.subtotal,
        "taxa_entrega": pedido.taxa_entrega,
        "total": pedido.total,
        "forma_pagamento": pedido.forma_pagamento.value if pedido.forma_pagamento else None,
        "troco_para": pedido.troco_para,
        "pago": bool(pedido.pago),
        "entregador_id": pedido.entregador_id,
        "entregador_nome": pedido.entregador.nome if pedido.entregador else None,
        "criado_em": _iso(pedido.criado_em),
        "atualizado_em": _iso(pedido.atualizado_em),
        "saiu_entrega_em": _iso(pedido.saiu_entrega_em),
        "finalizado_em": _iso(pedido.finalizado_em),
        "comprovante_enviado_em": _iso(pedido.comprovante_enviado_em),
        "cliente_nome": pedido.cliente.nome if pedido.cliente else None,
        "cliente_telefone": pedido.cliente.telefone if pedido.cliente else None,
        "itens": [
            {
                "id": item.id,
                "tipo": item.tipo.value,
                "nome": item.nome,
                "tamanho": item.tamanho,
                "quantidade": item.quantidade,
                "detalhes": item.detalhes,
            }
            for item in pedido.itens
        ],
    }


def _montar_pedido_out(pedido: models.Pedido) -> schemas.PedidoOut:
    out = schemas.PedidoOut.model_validate(pedido)
    out.cliente_nome = pedido.cliente.nome if pedido.cliente else None
    out.cliente_telefone = pedido.cliente.telefone if pedido.cliente else None
    out.entregador_nome = pedido.entregador.nome if pedido.entregador else None
    return out


def _carregar_pedido(db: Session, pedido_id: int) -> Optional[models.Pedido]:
    return (
        db.query(models.Pedido)
        .options(
            joinedload(models.Pedido.itens),
            joinedload(models.Pedido.cliente),
            joinedload(models.Pedido.entregador),
        )
        .filter(models.Pedido.id == pedido_id)
        .first()
    )


def _resolver_pizza_montada(db: Session, item: schemas.PedidoItemIn) -> Tuple[models.PedidoItem, List[str]]:
    """Calcula no servidor o preço da pizza montada (antes vinha do navegador).

    preço = base do tamanho + adicional da massa + adicional do molho
            + soma dos adicionais × porções. Retorna também os nomes oficiais
    dos ingredientes (um por porção) para a baixa de estoque.
    """
    if not item.tamanho:
        raise HTTPException(status_code=422, detail="Informe o tamanho (P, M ou G) da pizza montada")
    tamanho = db.get(models.TamanhoPizza, item.tamanho)
    if not tamanho:
        raise HTTPException(status_code=422, detail=f"Tamanho '{item.tamanho}' indisponível")
    if not item.ingredientes:
        raise HTTPException(status_code=422, detail="Pizza montada sem ingredientes. Monte a pizza novamente.")

    ativos = db.query(models.Ingrediente).filter(models.Ingrediente.ativo == 1).all()
    por_chave = {}
    for ing in ativos:
        por_chave[ing.nome.casefold()] = ing
        if ing.slug:
            por_chave[ing.slug.casefold()] = ing

    escolhidos = []
    for nome in item.ingredientes:
        ing = por_chave.get(nome.strip().casefold())
        if not ing:
            raise HTTPException(status_code=422, detail=f"Ingrediente '{nome}' indisponível. Monte a pizza novamente.")
        escolhidos.append(ing)

    massas = [i for i in escolhidos if i.tipo == models.TipoIngrediente.massa]
    molhos = [i for i in escolhidos if i.tipo == models.TipoIngrediente.molho]
    if len(massas) != 1 or len(molhos) != 1:
        raise HTTPException(status_code=422, detail="A pizza montada precisa de exatamente uma massa e um molho")

    porcoes = Counter(i.id for i in escolhidos if i.tipo == models.TipoIngrediente.topping)
    coberturas = {i.id: i for i in escolhidos}
    if any(qtd > MAX_PORCOES for qtd in porcoes.values()):
        raise HTTPException(status_code=422, detail=f"Máximo de {MAX_PORCOES} porções do mesmo adicional")

    preco = tamanho.preco_base + massas[0].preco_adicional + molhos[0].preco_adicional + sum(
        coberturas[i].preco_adicional * qtd for i, qtd in porcoes.items()
    )
    textos = [
        coberturas[i].nome if qtd == 1 else f"{coberturas[i].nome} ({qtd}×)"
        for i, qtd in porcoes.items()
    ]
    detalhes = f"{massas[0].nome} · {molhos[0].nome} · {', '.join(textos) or 'sem ingredientes extras'}"
    nomes_oficiais = [i.nome for i in escolhidos]
    return models.PedidoItem(
        tipo=item.tipo, nome="Pizza montada", tamanho=item.tamanho,
        preco_unitario=round(preco, 2), quantidade=item.quantidade, detalhes=detalhes,
    ), nomes_oficiais


def _resolver_item(db: Session, item: schemas.PedidoItemIn) -> Tuple[models.PedidoItem, Optional[List[str]]]:
    """Converte o item do carrinho em PedidoItem usando SEMPRE o preço do banco.

    O preço enviado pelo navegador nunca é usado: qualquer um pode editar o
    localStorage ou chamar a API direto.
    """
    if item.tipo == models.TipoItemPedido.cardapio:
        query = db.query(models.Pizza).filter(models.Pizza.ativo == 1)
        pizza = (
            query.filter(models.Pizza.slug == item.ref).first()
            if item.ref
            else query.filter(models.Pizza.nome == item.nome).first()
        )
        if not pizza:
            raise HTTPException(status_code=422, detail=f"'{item.nome}' não está disponível no cardápio")
        if not item.tamanho:
            raise HTTPException(status_code=422, detail=f"Informe o tamanho (P, M ou G) de '{pizza.nome}'")
        preco = {"P": pizza.preco_p, "M": pizza.preco_m, "G": pizza.preco_g}[item.tamanho]
        return models.PedidoItem(
            tipo=item.tipo, nome=pizza.nome, tamanho=item.tamanho,
            preco_unitario=preco, quantidade=item.quantidade, detalhes=item.detalhes,
        ), None

    if item.tipo == models.TipoItemPedido.bebida:
        ref = item.ref or item.nome
        bebida = (
            db.query(models.Bebida)
            .filter(models.Bebida.ativo == 1, or_(models.Bebida.slug == ref, models.Bebida.nome == ref))
            .first()
        )
        if not bebida:
            raise HTTPException(status_code=422, detail=f"'{item.nome}' não está disponível no cardápio")
        return models.PedidoItem(
            tipo=item.tipo, nome=bebida.nome, tamanho=None,
            preco_unitario=bebida.preco, quantidade=item.quantidade, detalhes=item.detalhes,
        ), None

    return _resolver_pizza_montada(db, item)


# ---------------------------------------------------------------------
# Criação de pedido — endpoint público (cliente não precisa de login)
# ---------------------------------------------------------------------

@router.post("/pedidos", response_model=schemas.PedidoOut, status_code=201)
async def criar_pedido(dados: schemas.PedidoIn, db: Session = Depends(get_db)):
    loja = status_loja(db)
    if not loja["aberto"]:
        raise HTTPException(status_code=409, detail=loja["mensagem"])
    if dados.forma_pagamento == models.FormaPagamento.pix and not pix_disponivel(db):
        raise HTTPException(status_code=422, detail="Pix indisponível no momento. Escolha outra forma de pagamento.")

    # Valida e precifica todos os itens ANTES de gravar qualquer coisa
    resolvidos = [_resolver_item(db, item) for item in dados.itens]
    itens = [r[0] for r in resolvidos]

    # Nomes oficiais escolhidos na pizza montada (por posição do item), para baixar os kg do estoque
    ingredientes_custom: Dict[int, List[str]] = {idx: r[1] for idx, r in enumerate(resolvidos) if r[1]}
    consumo = consumo_do_pedido(db, itens, ingredientes_custom)

    subtotal = round(sum(i.preco_unitario * i.quantidade for i in itens), 2)
    bairro = None
    if dados.tipo_entrega == models.TipoEntrega.delivery:
        bairro = db.get(models.BairroEntrega, dados.bairro_id)
        if not bairro or not bairro.ativo:
            raise HTTPException(status_code=422, detail="Bairro não atendido. Escolha outro bairro ou retire no balcão.")
    taxa_entrega = bairro.taxa if bairro else 0.0
    total = round(subtotal + taxa_entrega, 2)

    if dados.troco_para is not None and dados.troco_para < total:
        raise HTTPException(
            status_code=422,
            detail=f"O valor para troco (R$ {dados.troco_para:.2f}) é menor que o total do pedido (R$ {total:.2f})".replace(".", ","),
        )

    try:
        # Busca cliente existente pelo telefone, ou cria um novo cadastro rápido
        cliente = (
            db.query(models.Cliente).filter(models.Cliente.telefone == dados.cliente_telefone).first()
        )
        if cliente:
            cliente.nome = dados.cliente_nome
            if dados.endereco_entrega:
                cliente.endereco = dados.endereco_entrega
        else:
            cliente = models.Cliente(
                nome=dados.cliente_nome,
                telefone=dados.cliente_telefone,
                endereco=dados.endereco_entrega,
            )
            db.add(cliente)

        pedido = models.Pedido(
            cliente=cliente,
            tipo_entrega=dados.tipo_entrega,
            endereco_entrega=dados.endereco_entrega,
            bairro_id=bairro.id if bairro else None,
            bairro_nome=bairro.nome if bairro else None,
            status=models.StatusPedido.pendente,
            subtotal=subtotal,
            taxa_entrega=taxa_entrega,
            total=total,
            observacoes=dados.observacoes,
            forma_pagamento=dados.forma_pagamento,
            troco_para=dados.troco_para,
            pago=0,
            codigo_acompanhamento=secrets.token_urlsafe(12),
            itens=itens,
        )
        db.add(pedido)
        db.flush()  # gera pedido.id para o histórico do estoque
        estoque_mudou = baixar_pedido(db, pedido, consumo)
        db.commit()  # cliente + pedido + itens + baixa de estoque numa única transação
    except EstoqueInsuficiente as e:
        db.rollback()  # nada é gravado: nem cliente, nem pedido, nem baixa
        raise HTTPException(status_code=409, detail=e.mensagem)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Não foi possível registrar o pedido. Tente novamente.")

    # Recarrega com relacionamentos para serializar corretamente
    pedido = _carregar_pedido(db, pedido.id)

    # O pedido já está salvo; o broadcast nunca derruba a resposta ao cliente
    await manager.broadcast({"evento": "novo_pedido", "pedido": _serializar_pedido(pedido)})
    await avisar_entregadores(pedido)
    if estoque_mudou:
        await manager.broadcast(evento_estoque(db))

    return _montar_pedido_out(pedido)


# ---------------------------------------------------------------------
# Acompanhamento — público, pelo código secreto do link (não pelo número)
# ---------------------------------------------------------------------

def _pedido_pelo_codigo(db: Session, codigo: str) -> models.Pedido:
    pedido = (
        db.query(models.Pedido)
        .options(joinedload(models.Pedido.itens), joinedload(models.Pedido.cliente), joinedload(models.Pedido.entregador))
        .filter(models.Pedido.codigo_acompanhamento == codigo)
        .first()
    )
    if not pedido or len(codigo) < 12:
        raise HTTPException(status_code=404, detail="Pedido não encontrado. Confira o link recebido.")
    return pedido


@router.get("/pedidos/acompanhar/{codigo}", response_model=schemas.AcompanhamentoOut)
def acompanhar_pedido(codigo: str, db: Session = Depends(get_db)):
    pedido = _pedido_pelo_codigo(db, codigo)
    nome = (pedido.cliente.nome if pedido.cliente else "").split(" ")[0]
    return schemas.AcompanhamentoOut(
        id=pedido.id,
        status=pedido.status,
        tipo_entrega=pedido.tipo_entrega,
        cliente_primeiro_nome=nome,
        bairro_nome=pedido.bairro_nome,
        entregador_nome=pedido.entregador.nome.split(" ")[0] if pedido.entregador else None,
        forma_pagamento=pedido.forma_pagamento,
        troco_para=pedido.troco_para,
        pago=bool(pedido.pago),
        subtotal=pedido.subtotal,
        taxa_entrega=pedido.taxa_entrega,
        total=pedido.total,
        criado_em=pedido.criado_em,
        atualizado_em=pedido.atualizado_em,
        saiu_entrega_em=pedido.saiu_entrega_em,
        finalizado_em=pedido.finalizado_em,
        comprovante_enviado=bool(pedido.comprovante_arquivo),
        itens=[
            schemas.AcompanhamentoItemOut(nome=i.nome, tamanho=i.tamanho, quantidade=i.quantidade, detalhes=i.detalhes)
            for i in pedido.itens
        ],
    )


@router.get("/pedidos/acompanhar/{codigo}/pix", response_model=schemas.PixPedidoOut)
def pix_do_link(codigo: str, db: Session = Depends(get_db)):
    """Chave, "copia e cola" e QR Code com o valor exato do pedido."""
    pedido = _pedido_pelo_codigo(db, codigo)
    if pedido.forma_pagamento != models.FormaPagamento.pix:
        raise HTTPException(status_code=409, detail="Este pedido não é pago com Pix")
    if not pix_disponivel(db):
        raise HTTPException(status_code=409, detail="Pix indisponível no momento. Fale com a pizzaria.")
    return pix_do_pedido(db, pedido)


@router.post("/pedidos/acompanhar/{codigo}/comprovante", status_code=201)
async def enviar_comprovante(codigo: str, arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    """O cliente envia o comprovante do Pix (foto ou PDF); a cozinha é avisada na hora."""
    pedido = _pedido_pelo_codigo(db, codigo)
    if pedido.forma_pagamento != models.FormaPagamento.pix:
        raise HTTPException(status_code=409, detail="Este pedido não é pago com Pix")
    if pedido.status == models.StatusPedido.cancelado:
        raise HTTPException(status_code=409, detail="Este pedido foi cancelado")
    if pedido.pago:
        raise HTTPException(status_code=409, detail="A pizzaria já confirmou este pagamento")

    conteudo = await arquivo.read(LIMITE_COMPROVANTE + 1)
    if len(conteudo) > LIMITE_COMPROVANTE:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (máximo 5 MB)")
    extensao = _tipo_do_arquivo(conteudo)
    if not extensao:
        raise HTTPException(status_code=415, detail="Envie uma foto (JPG, PNG ou WEBP) ou um PDF do comprovante")

    PASTA_COMPROVANTES.mkdir(parents=True, exist_ok=True)
    nome = f"{secrets.token_hex(16)}.{extensao}"  # nome aleatório: não dá para adivinhar nem sobrescrever outro
    (PASTA_COMPROVANTES / nome).write_bytes(conteudo)
    anterior = pedido.comprovante_arquivo
    pedido.comprovante_arquivo = nome
    pedido.comprovante_enviado_em = datetime.utcnow()
    db.commit()
    if anterior and NOME_ARQUIVO.match(anterior):
        (PASTA_COMPROVANTES / anterior).unlink(missing_ok=True)  # reenvio substitui o anterior

    pedido = _carregar_pedido(db, pedido.id)
    await manager.broadcast({"evento": "comprovante_recebido", "pedido": _serializar_pedido(pedido)})
    return {"ok": True, "enviado_em": _iso(pedido.comprovante_enviado_em)}


# ---------------------------------------------------------------------
# Pedido completo — só equipe (antes era público e expunha telefone/endereço)
# ---------------------------------------------------------------------

@router.get("/cozinha/pedidos/{pedido_id}/comprovante")
def baixar_comprovante(
    pedido_id: int,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    pedido = db.get(models.Pedido, pedido_id)
    if not pedido or not pedido.comprovante_arquivo or not NOME_ARQUIVO.match(pedido.comprovante_arquivo):
        raise HTTPException(status_code=404, detail="Este pedido não tem comprovante")
    caminho = PASTA_COMPROVANTES / pedido.comprovante_arquivo
    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Arquivo do comprovante não encontrado")
    extensao = caminho.suffix.lstrip(".")
    return FileResponse(caminho, media_type=MIME[extensao], filename=f"comprovante-pedido-{pedido_id}.{extensao}")


@router.get("/pedidos/{pedido_id}", response_model=schemas.PedidoOut)
def obter_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    pedido = _carregar_pedido(db, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return _montar_pedido_out(pedido)


# ---------------------------------------------------------------------
# Fila da cozinha — protegida por login (staff)
# ---------------------------------------------------------------------

@router.get("/cozinha/pedidos", response_model=List[schemas.PedidoOut])
def listar_fila(
    status: Optional[models.StatusPedido] = None,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    query = db.query(models.Pedido).options(
        joinedload(models.Pedido.itens), joinedload(models.Pedido.cliente), joinedload(models.Pedido.entregador)
    )
    if status:
        query = query.filter(models.Pedido.status == status)
    else:
        # por padrão: tudo que está em andamento + o que foi entregue/cancelado hoje
        # (a coluna "Finalizados" do Kanban mostra só o turno atual)
        query = query.filter(
            or_(
                models.Pedido.status.in_(STATUS_EM_ANDAMENTO),
                models.Pedido.atualizado_em >= inicio_do_dia_em_utc(hoje_local()),
            )
        )
    pedidos = query.order_by(models.Pedido.criado_em.asc()).all()
    return [_montar_pedido_out(p) for p in pedidos]


@router.patch("/cozinha/pedidos/{pedido_id}/status", response_model=schemas.PedidoOut)
async def atualizar_status(
    pedido_id: int,
    dados: schemas.StatusUpdateIn,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    pedido = _carregar_pedido(db, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    novo = dados.status
    if novo == models.StatusPedido.saiu_entrega:
        if pedido.tipo_entrega != models.TipoEntrega.delivery:
            raise HTTPException(status_code=422, detail="Pedido para retirada não sai para entrega")
        if dados.entregador_id is not None:
            entregador = db.get(models.Entregador, dados.entregador_id)
            if not entregador or not entregador.ativo:
                raise HTTPException(status_code=422, detail="Entregador não encontrado")
            pedido.entregador_id = entregador.id
        pedido.saiu_entrega_em = datetime.utcnow()
    elif novo in (models.StatusPedido.pendente, models.StatusPedido.em_preparo, models.StatusPedido.pronto):
        pedido.saiu_entrega_em = None  # voltou para a cozinha
    pedido.finalizado_em = datetime.utcnow() if novo in STATUS_FINAIS else None

    status_anterior = pedido.status
    pedido.status = novo
    # cancelou → devolve ao estoque o que foi baixado automaticamente; reabriu → baixa de novo
    try:
        estoque_mudou = ajustar_por_mudanca_de_status(db, pedido, status_anterior, usuario_atual.id)
    except EstoqueInsuficiente as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Não dá para reabrir o pedido. {e.mensagem}")
    db.commit()
    db.expire_all()  # recarrega o entregador recém-associado
    pedido = _carregar_pedido(db, pedido_id)

    await manager.broadcast({"evento": "status_atualizado", "pedido": _serializar_pedido(pedido)})
    await avisar_entregadores(pedido)  # "pronto" toca no celular dos entregadores
    if estoque_mudou:
        await manager.broadcast(evento_estoque(db))

    return _montar_pedido_out(pedido)


@router.patch("/cozinha/pedidos/{pedido_id}/pagamento", response_model=schemas.PedidoOut)
async def atualizar_pagamento(
    pedido_id: int,
    dados: schemas.PagamentoIn,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    pedido = _carregar_pedido(db, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    pedido.pago = 1 if dados.pago else 0
    pedido.pago_em = datetime.utcnow() if dados.pago else None
    db.commit()
    pedido = _carregar_pedido(db, pedido_id)
    await manager.broadcast({"evento": "status_atualizado", "pedido": _serializar_pedido(pedido)})
    await avisar_entregadores(pedido)
    return _montar_pedido_out(pedido)


@router.get("/cozinha/entregadores", response_model=List[schemas.EntregadorOut])
def entregadores_ativos(db: Session = Depends(get_db), usuario_atual: models.Usuario = Depends(get_current_user)):
    return (
        db.query(models.Entregador)
        .filter(models.Entregador.ativo == 1)
        .order_by(func.lower(models.Entregador.nome))
        .all()
    )


@router.put("/cozinha/pausa", response_model=schemas.LojaStatusOut)
async def pausar_pedidos(
    dados: schemas.PausaIn,
    db: Session = Depends(get_db),
    usuario_atual: models.Usuario = Depends(get_current_user),
):
    """A cozinha pausa os pedidos do site quando está sobrecarregada."""
    definir_pausa(db, dados.pausado)
    db.commit()
    loja = status_loja(db)
    await manager.broadcast({"evento": "loja_atualizada", "loja": loja})
    return loja


# ---------------------------------------------------------------------
# WebSocket — atualização em tempo real da tela da cozinha
# Uso no front: new WebSocket(`ws://host:8002/ws/cozinha?token=${jwt}`)
# (o navegador não permite header Authorization em WebSocket)
# ---------------------------------------------------------------------

@router.websocket("/ws/cozinha")
async def websocket_cozinha(websocket: WebSocket, token: Optional[str] = None):
    await websocket.accept()

    db = SessionLocal()
    try:
        usuario = usuario_do_token(token, db) if token else None
    finally:
        db.close()

    if usuario is None:
        await websocket.close(code=WS_CODIGO_NAO_AUTORIZADO, reason="Token inválido ou expirado")
        return

    await manager.connect(websocket)
    try:
        await websocket.send_json({"evento": "conectado", "usuario": usuario.nome})
        while True:
            # heartbeat: o front manda "ping" periodicamente para a conexão não
            # ser derrubada por proxies/Nginx por inatividade
            mensagem = await websocket.receive_text()
            if mensagem == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
