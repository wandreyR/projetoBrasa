from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..database import get_db, SessionLocal
from ..auth import get_current_user, usuario_do_token
from ..tempo import hoje_local, inicio_do_dia_em_utc
from ..websocket_manager import manager

router = APIRouter(tags=["Pedidos"])

TAXA_ENTREGA_PADRAO = 6.0

# Código de fechamento do WebSocket quando o token é inválido/ausente.
# Faixa 4000-4999 é livre para uso da aplicação; o front usa esse código
# para saber que precisa pedir login de novo (em vez de ficar reconectando).
WS_CODIGO_NAO_AUTORIZADO = 4401


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
        "observacoes": pedido.observacoes,
        "subtotal": pedido.subtotal,
        "taxa_entrega": pedido.taxa_entrega,
        "total": pedido.total,
        "criado_em": pedido.criado_em.isoformat(),
        "atualizado_em": pedido.atualizado_em.isoformat() if pedido.atualizado_em else None,
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
    return out


def _carregar_pedido(db: Session, pedido_id: int) -> Optional[models.Pedido]:
    return (
        db.query(models.Pedido)
        .options(joinedload(models.Pedido.itens), joinedload(models.Pedido.cliente))
        .filter(models.Pedido.id == pedido_id)
        .first()
    )


def _resolver_item(db: Session, item: schemas.PedidoItemIn) -> models.PedidoItem:
    """Converte o item do carrinho em PedidoItem usando o preço do BANCO.

    O preço enviado pelo navegador nunca é confiável (qualquer um pode editar
    o localStorage ou chamar a API direto). Para pizzas do cardápio e bebidas
    buscamos o valor oficial; só a pizza montada ainda usa o valor calculado
    no front, porque os preços base por tamanho dela ainda não estão no banco.
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
        )

    if item.tipo == models.TipoItemPedido.bebida:
        bebida = (
            db.query(models.Bebida)
            .filter(models.Bebida.ativo == 1, models.Bebida.nome == (item.ref or item.nome))
            .first()
        )
        if not bebida:
            raise HTTPException(status_code=422, detail=f"'{item.nome}' não está disponível no cardápio")
        return models.PedidoItem(
            tipo=item.tipo, nome=bebida.nome, tamanho=None,
            preco_unitario=bebida.preco, quantidade=item.quantidade, detalhes=item.detalhes,
        )

    # Pizza montada
    if not item.tamanho:
        raise HTTPException(status_code=422, detail="Informe o tamanho (P, M ou G) da pizza montada")
    return models.PedidoItem(
        tipo=item.tipo, nome=item.nome, tamanho=item.tamanho,
        preco_unitario=item.preco_unitario, quantidade=item.quantidade, detalhes=item.detalhes,
    )


# ---------------------------------------------------------------------
# Criação de pedido — endpoint público (cliente não precisa de login)
# ---------------------------------------------------------------------

@router.post("/pedidos", response_model=schemas.PedidoOut, status_code=201)
async def criar_pedido(dados: schemas.PedidoIn, db: Session = Depends(get_db)):
    # Valida e precifica todos os itens ANTES de gravar qualquer coisa
    itens = [_resolver_item(db, item) for item in dados.itens]

    subtotal = round(sum(i.preco_unitario * i.quantidade for i in itens), 2)
    taxa_entrega = TAXA_ENTREGA_PADRAO if dados.tipo_entrega == models.TipoEntrega.delivery else 0.0

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
            status=models.StatusPedido.pendente,
            subtotal=subtotal,
            taxa_entrega=taxa_entrega,
            total=round(subtotal + taxa_entrega, 2),
            observacoes=dados.observacoes,
            itens=itens,
        )
        db.add(pedido)
        db.commit()  # cliente + pedido + itens numa única transação
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Não foi possível registrar o pedido. Tente novamente.")

    # Recarrega com relacionamentos para serializar corretamente
    pedido = _carregar_pedido(db, pedido.id)

    # O pedido já está salvo; o broadcast nunca derruba a resposta ao cliente
    await manager.broadcast({"evento": "novo_pedido", "pedido": _serializar_pedido(pedido)})

    return _montar_pedido_out(pedido)


# ---------------------------------------------------------------------
# Consulta de status — pública (cliente acompanha o próprio pedido)
# ---------------------------------------------------------------------

@router.get("/pedidos/{pedido_id}", response_model=schemas.PedidoOut)
def obter_pedido(pedido_id: int, db: Session = Depends(get_db)):
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
        joinedload(models.Pedido.itens), joinedload(models.Pedido.cliente)
    )
    if status:
        query = query.filter(models.Pedido.status == status)
    else:
        # por padrão: tudo que está em andamento + o que foi entregue/cancelado hoje
        # (a coluna "Entregues" do Kanban mostra só o turno atual)
        query = query.filter(
            or_(
                models.Pedido.status.in_([
                    models.StatusPedido.pendente,
                    models.StatusPedido.em_preparo,
                    models.StatusPedido.pronto,
                ]),
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

    pedido.status = dados.status
    db.commit()
    pedido = _carregar_pedido(db, pedido_id)

    await manager.broadcast({"evento": "status_atualizado", "pedido": _serializar_pedido(pedido)})

    return _montar_pedido_out(pedido)


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
