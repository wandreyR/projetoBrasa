"""Área do entregador: login pelo celular, pedidos prontos, minhas entregas e baixa da entrega."""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import criar_token_entregador, entregador_do_token, get_entregador_atual, verificar_senha
from ..database import get_db, SessionLocal
from ..tempo import hoje_local, inicio_do_dia_em_utc
from ..websocket_manager import avisar_entregadores, manager, manager_entregadores
from . import pedidos as rotas_pedidos

router = APIRouter(tags=["Entregador"])

WS_CODIGO_NAO_AUTORIZADO = 4401


def _entrega(p: models.Pedido, entregador_id: int) -> schemas.EntregaOut:
    return schemas.EntregaOut(
        id=p.id,
        status=p.status,
        cliente_nome=p.cliente.nome if p.cliente else "",
        cliente_telefone=p.cliente.telefone if p.cliente else "",
        endereco_entrega=p.endereco_entrega,
        bairro_nome=p.bairro_nome,
        observacoes=p.observacoes,
        itens=[schemas.AcompanhamentoItemOut(nome=i.nome, tamanho=i.tamanho, quantidade=i.quantidade, detalhes=i.detalhes)
               for i in p.itens],
        total=p.total,
        taxa_entrega=p.taxa_entrega,
        forma_pagamento=p.forma_pagamento,
        troco_para=p.troco_para,
        pago=bool(p.pago),
        criado_em=p.criado_em,
        atualizado_em=p.atualizado_em,
        saiu_entrega_em=p.saiu_entrega_em,
        minha=p.entregador_id == entregador_id,
    )


def _consulta_entregas(db: Session):
    return (
        db.query(models.Pedido)
        .options(joinedload(models.Pedido.itens), joinedload(models.Pedido.cliente))
        .filter(models.Pedido.tipo_entrega == models.TipoEntrega.delivery)
    )


async def _avisar_todos(db: Session, pedido_id: int):
    """Cozinha vê a mudança no Kanban; entregadores atualizam o painel."""
    pedido = rotas_pedidos._carregar_pedido(db, pedido_id)
    await manager.broadcast({"evento": "status_atualizado", "pedido": rotas_pedidos._serializar_pedido(pedido)})
    await avisar_entregadores(pedido)
    return pedido


# ---------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------

@router.post("/auth/entregador/login", response_model=schemas.TokenEntregadorOut)
def login_entregador(dados: schemas.LoginEntregadorIn, db: Session = Depends(get_db)):
    digitos = re.sub(r"\D", "", dados.telefone)
    if len(digitos) > 11 and digitos.startswith("55"):
        digitos = digitos[2:]
    entregador = next(
        (e for e in db.query(models.Entregador).filter(models.Entregador.senha_hash.isnot(None))
         if re.sub(r"\D", "", e.telefone or "") == digitos),
        None,
    )
    if not entregador or not verificar_senha(dados.senha, entregador.senha_hash):
        raise HTTPException(status_code=401, detail="Celular ou senha incorretos")
    if not entregador.ativo:
        raise HTTPException(status_code=403, detail="Seu acesso está desativado. Fale com a pizzaria.")
    return schemas.TokenEntregadorOut(access_token=criar_token_entregador(entregador), nome=entregador.nome)


# ---------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------

@router.get("/entregador/painel", response_model=schemas.PainelEntregadorOut)
def painel(db: Session = Depends(get_db), eu: models.Entregador = Depends(get_entregador_atual)):
    prontos = (
        _consulta_entregas(db)
        .filter(models.Pedido.status == models.StatusPedido.pronto)
        .order_by(models.Pedido.atualizado_em.asc())  # quem ficou pronto antes sai antes
        .all()
    )
    minhas = (
        _consulta_entregas(db)
        .filter(models.Pedido.status == models.StatusPedido.saiu_entrega, models.Pedido.entregador_id == eu.id)
        .order_by(models.Pedido.saiu_entrega_em.asc())
        .all()
    )
    na_cozinha = (
        db.query(models.Pedido)
        .filter(models.Pedido.tipo_entrega == models.TipoEntrega.delivery,
                models.Pedido.status.in_([models.StatusPedido.pendente, models.StatusPedido.em_preparo]))
        .order_by(models.Pedido.criado_em.asc())
        .all()
    )
    hoje = (
        db.query(models.Pedido)
        .filter(models.Pedido.entregador_id == eu.id,
                models.Pedido.status == models.StatusPedido.entregue,
                models.Pedido.finalizado_em >= inicio_do_dia_em_utc(hoje_local()))
        .all()
    )
    return schemas.PainelEntregadorOut(
        entregador_nome=eu.nome,
        # pronto e já designado pela cozinha para outro entregador não aparece
        prontos=[_entrega(p, eu.id) for p in prontos if p.entregador_id in (None, eu.id)],
        minhas=[_entrega(p, eu.id) for p in minhas],
        na_cozinha=[schemas.NaCozinhaOut(id=p.id, status=p.status, bairro_nome=p.bairro_nome, criado_em=p.criado_em)
                    for p in na_cozinha],
        entregues_hoje=len(hoje),
        taxas_hoje=round(sum(p.taxa_entrega for p in hoje), 2),
    )


# ---------------------------------------------------------------------
# Ações nas entregas
# ---------------------------------------------------------------------

def _pedido_para_entregar(db: Session, pedido_id: int) -> models.Pedido:
    # trava a linha: dois entregadores tocando em "Peguei" ao mesmo tempo não levam o mesmo pedido
    pedido = db.query(models.Pedido).filter(models.Pedido.id == pedido_id).with_for_update().first()
    if not pedido or pedido.tipo_entrega != models.TipoEntrega.delivery:
        raise HTTPException(status_code=404, detail="Entrega não encontrada")
    return pedido


@router.post("/entregador/pedidos/{pedido_id}/sair", response_model=schemas.EntregaOut)
async def sair_para_entrega(pedido_id: int, db: Session = Depends(get_db), eu: models.Entregador = Depends(get_entregador_atual)):
    pedido = _pedido_para_entregar(db, pedido_id)
    if pedido.status == models.StatusPedido.saiu_entrega and pedido.entregador_id == eu.id:
        db.rollback()
        return _entrega(rotas_pedidos._carregar_pedido(db, pedido_id), eu.id)  # toque repetido
    if pedido.entregador_id not in (None, eu.id) or pedido.status == models.StatusPedido.saiu_entrega:
        db.rollback()
        raise HTTPException(status_code=409, detail="Outro entregador já pegou este pedido")
    if pedido.status != models.StatusPedido.pronto:
        db.rollback()
        raise HTTPException(status_code=409, detail="Este pedido ainda não está pronto")
    pedido.entregador_id = eu.id
    pedido.status = models.StatusPedido.saiu_entrega
    pedido.saiu_entrega_em = datetime.utcnow()
    db.commit()
    return _entrega(await _avisar_todos(db, pedido_id), eu.id)


@router.post("/entregador/pedidos/{pedido_id}/entregue", response_model=schemas.EntregaOut)
async def marcar_entregue(
    pedido_id: int,
    dados: schemas.EntregueIn,
    db: Session = Depends(get_db),
    eu: models.Entregador = Depends(get_entregador_atual),
):
    pedido = _pedido_para_entregar(db, pedido_id)
    if pedido.entregador_id != eu.id or pedido.status != models.StatusPedido.saiu_entrega:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esta entrega não está com você")
    pedido.status = models.StatusPedido.entregue
    pedido.finalizado_em = datetime.utcnow()
    if dados.recebi_pagamento and not pedido.pago:
        pedido.pago = 1
        pedido.pago_em = datetime.utcnow()
    db.commit()
    return _entrega(await _avisar_todos(db, pedido_id), eu.id)


@router.post("/entregador/pedidos/{pedido_id}/devolver", response_model=schemas.EntregaOut)
async def devolver_entrega(pedido_id: int, db: Session = Depends(get_db), eu: models.Entregador = Depends(get_entregador_atual)):
    """Não conseguiu entregar (cliente ausente, endereço errado…): volta para "Prontos" na cozinha."""
    pedido = _pedido_para_entregar(db, pedido_id)
    if pedido.entregador_id != eu.id or pedido.status != models.StatusPedido.saiu_entrega:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esta entrega não está com você")
    pedido.status = models.StatusPedido.pronto
    pedido.entregador_id = None
    pedido.saiu_entrega_em = None
    db.commit()
    return _entrega(await _avisar_todos(db, pedido_id), eu.id)


# ---------------------------------------------------------------------
# Tempo real: ws://host:8002/ws/entregador?token=<jwt do entregador>
# ---------------------------------------------------------------------

@router.websocket("/ws/entregador")
async def websocket_entregador(websocket: WebSocket, token: Optional[str] = None):
    await websocket.accept()
    db = SessionLocal()
    try:
        eu = entregador_do_token(token, db) if token else None
        nome = eu.nome if eu else None
    finally:
        db.close()
    if eu is None:
        await websocket.close(code=WS_CODIGO_NAO_AUTORIZADO, reason="Acesso inválido ou expirado")
        return

    await manager_entregadores.connect(websocket)
    try:
        await websocket.send_json({"evento": "conectado", "entregador": nome})
        while True:
            if await websocket.receive_text() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        manager_entregadores.disconnect(websocket)
