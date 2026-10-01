from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import exigir_admin, get_current_user
from ..database import get_db
from ..estoque_service import evento_estoque, itens_em_alerta, movimentar, serializar_item
from ..websocket_manager import manager

# Cozinha e dono usam o estoque; só o dono exclui itens
router = APIRouter(prefix="/estoque", tags=["Estoque"], dependencies=[Depends(get_current_user)])


def _item_ou_404(db: Session, item_id: int) -> models.EstoqueItem:
    item = (
        db.query(models.EstoqueItem)
        .options(joinedload(models.EstoqueItem.bebida))
        .filter(models.EstoqueItem.id == item_id, models.EstoqueItem.ativo == 1)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item de estoque não encontrado")
    return item


def _validar_bebida(db: Session, bebida_id: Optional[int], item_id: Optional[int] = None):
    if bebida_id is None:
        return
    if not db.get(models.Bebida, bebida_id):
        raise HTTPException(status_code=422, detail="Bebida não encontrada")
    outro = (
        db.query(models.EstoqueItem)
        .filter(models.EstoqueItem.bebida_id == bebida_id, models.EstoqueItem.id != (item_id or 0))
        .first()
    )
    if outro:
        raise HTTPException(status_code=409, detail=f"Essa bebida já está ligada ao item '{outro.nome}'")


def _nome_em_uso(db: Session, nome: str, item_id: Optional[int] = None) -> Optional[models.EstoqueItem]:
    # comparação em Python: casefold trata acentos ("Óleo" == "óleo") em qualquer banco
    alvo = nome.casefold()
    return next(
        (i for i in db.query(models.EstoqueItem) if i.nome.casefold() == alvo and i.id != item_id),
        None,
    )


async def _avisar_mudanca(db: Session):
    await manager.broadcast(evento_estoque(db))


# ---------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------

@router.get("/itens", response_model=List[schemas.EstoqueItemOut])
def listar_itens(db: Session = Depends(get_db)):
    itens = (
        db.query(models.EstoqueItem)
        .options(joinedload(models.EstoqueItem.bebida))
        .filter(models.EstoqueItem.ativo == 1)
        .order_by(models.EstoqueItem.nome)
        .all()
    )
    return [serializar_item(i) for i in itens]


@router.get("/alertas", response_model=List[schemas.EstoqueItemOut])
def listar_alertas(db: Session = Depends(get_db)):
    return [serializar_item(i) for i in itens_em_alerta(db)]


@router.post("/itens", response_model=schemas.EstoqueItemOut, status_code=201)
async def criar_item(
    dados: schemas.EstoqueItemCriarIn,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(get_current_user),
):
    existente = _nome_em_uso(db, dados.nome)
    if existente and existente.ativo:
        raise HTTPException(status_code=409, detail=f"Já existe um item chamado '{existente.nome}'")
    _validar_bebida(db, dados.bebida_id, existente.id if existente else None)

    minimo = dados.minimo if dados.minimo is not None else models.MINIMO_PADRAO[dados.unidade]
    if existente:
        # item excluído antes com o mesmo nome: reativa em vez de duplicar
        item = existente
        item.ativo, item.unidade, item.minimo, item.bebida_id = 1, dados.unidade, minimo, dados.bebida_id
        delta = dados.quantidade - item.quantidade
    else:
        item = models.EstoqueItem(nome=dados.nome, unidade=dados.unidade, quantidade=0,
                                  minimo=minimo, bebida_id=dados.bebida_id)
        db.add(item)
        delta = dados.quantidade

    if delta:
        movimentar(db, item, delta, models.TipoMovimentacao.ajuste,
                   usuario_id=usuario.id, observacao="Cadastro do item")
    db.commit()
    item = _item_ou_404(db, item.id)
    await _avisar_mudanca(db)
    return serializar_item(item)


@router.put("/itens/{item_id}", response_model=schemas.EstoqueItemOut)
async def atualizar_item(item_id: int, dados: schemas.EstoqueItemIn, db: Session = Depends(get_db)):
    item = _item_ou_404(db, item_id)
    if _nome_em_uso(db, dados.nome, item.id):
        raise HTTPException(status_code=409, detail="Já existe outro item com esse nome")
    if dados.unidade != item.unidade and item.quantidade:
        raise HTTPException(status_code=422, detail="Zere o saldo (ajuste para 0) antes de trocar a unidade")
    _validar_bebida(db, dados.bebida_id, item.id)

    item.nome = dados.nome
    item.unidade = dados.unidade
    item.minimo = dados.minimo if dados.minimo is not None else models.MINIMO_PADRAO[dados.unidade]
    item.bebida_id = dados.bebida_id
    db.commit()
    item = _item_ou_404(db, item.id)
    await _avisar_mudanca(db)
    return serializar_item(item)


@router.delete("/itens/{item_id}", status_code=204, dependencies=[Depends(exigir_admin)])
async def excluir_item(item_id: int, db: Session = Depends(get_db)):
    item = _item_ou_404(db, item_id)
    # exclusão lógica: o histórico de movimentações continua apontando para o item
    item.ativo = 0
    item.bebida_id = None
    db.query(models.ConsumoIngrediente).filter(models.ConsumoIngrediente.estoque_item_id == item.id).delete()
    db.commit()
    await _avisar_mudanca(db)


# ---------------------------------------------------------------------
# Movimentações manuais (entrada, saída, ajuste de contagem)
# ---------------------------------------------------------------------

@router.post("/itens/{item_id}/movimentar", response_model=schemas.EstoqueItemOut)
async def movimentar_item(
    item_id: int,
    dados: schemas.MovimentarIn,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(get_current_user),
):
    item = _item_ou_404(db, item_id)
    if item.unidade == models.UnidadeEstoque.un and dados.quantidade != int(dados.quantidade):
        raise HTTPException(status_code=422, detail="Itens em unidades não aceitam quantidade fracionada")

    if dados.tipo == "entrada":
        delta = dados.quantidade
    elif dados.tipo == "saida":
        if dados.quantidade > item.quantidade + 1e-9:
            raise HTTPException(
                status_code=422,
                detail=f"Saída maior que o saldo ({item.quantidade:g} {item.unidade.value}). "
                       "Se a contagem estiver errada, use Contagem.",
            )
        delta = -dados.quantidade
    else:  # ajuste: a quantidade informada é a nova contagem
        delta = dados.quantidade - item.quantidade
        if not delta:
            return serializar_item(item)

    movimentar(db, item, delta, models.TipoMovimentacao(dados.tipo),
               usuario_id=usuario.id, observacao=dados.observacao)
    db.commit()
    item = _item_ou_404(db, item.id)
    await _avisar_mudanca(db)
    return serializar_item(item)


@router.get("/movimentacoes", response_model=List[schemas.MovimentacaoOut])
def listar_movimentacoes(item_id: Optional[int] = None, limite: int = 100, db: Session = Depends(get_db)):
    query = db.query(models.MovimentacaoEstoque).options(
        joinedload(models.MovimentacaoEstoque.estoque_item), joinedload(models.MovimentacaoEstoque.usuario)
    )
    if item_id:
        query = query.filter(models.MovimentacaoEstoque.estoque_item_id == item_id)
    movs = query.order_by(models.MovimentacaoEstoque.id.desc()).limit(min(max(limite, 1), 500)).all()
    return [
        schemas.MovimentacaoOut(
            id=m.id,
            estoque_item_id=m.estoque_item_id,
            item_nome=m.estoque_item.nome,
            unidade=m.estoque_item.unidade,
            tipo=m.tipo.value,
            quantidade=m.quantidade,
            saldo=m.saldo,
            pedido_id=m.pedido_id,
            usuario_nome=m.usuario.nome if m.usuario else None,
            observacao=m.observacao,
            criado_em=m.criado_em,
        )
        for m in movs
    ]


# ---------------------------------------------------------------------
# Receita da pizza montada (consumo por ingrediente)
# ---------------------------------------------------------------------

@router.get("/consumo", response_model=List[schemas.ConsumoOut])
def listar_consumo(db: Session = Depends(get_db)):
    receitas = {c.ingrediente_id: c for c in db.query(models.ConsumoIngrediente)}
    ingredientes = (
        db.query(models.Ingrediente)
        .filter(models.Ingrediente.ativo == 1)
        .order_by(models.Ingrediente.tipo, models.Ingrediente.nome)
        .all()
    )
    saida = []
    for ing in ingredientes:
        r = receitas.get(ing.id)
        saida.append(schemas.ConsumoOut(
            ingrediente_id=ing.id,
            ingrediente_nome=ing.nome,
            ingrediente_tipo=ing.tipo,
            estoque_item_id=r.estoque_item_id if r else None,
            qtd_p=r.qtd_p if r else 0,
            qtd_m=r.qtd_m if r else 0,
            qtd_g=r.qtd_g if r else 0,
        ))
    return saida


@router.put("/consumo/{ingrediente_id}", response_model=schemas.ConsumoOut)
def definir_consumo(ingrediente_id: int, dados: schemas.ConsumoIn, db: Session = Depends(get_db)):
    ing = db.get(models.Ingrediente, ingrediente_id)
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    receita = db.get(models.ConsumoIngrediente, ingrediente_id)
    if dados.estoque_item_id is None:
        if receita:
            db.delete(receita)
        db.commit()
        return schemas.ConsumoOut(ingrediente_id=ing.id, ingrediente_nome=ing.nome, ingrediente_tipo=ing.tipo)

    item = _item_ou_404(db, dados.estoque_item_id)
    if item.unidade != models.UnidadeEstoque.kg:
        raise HTTPException(status_code=422, detail="A pizza montada só baixa itens controlados em kg")
    if not receita:
        receita = models.ConsumoIngrediente(ingrediente_id=ing.id)
        db.add(receita)
    receita.estoque_item_id = item.id
    receita.qtd_p, receita.qtd_m, receita.qtd_g = dados.qtd_p, dados.qtd_m, dados.qtd_g
    db.commit()
    return schemas.ConsumoOut(
        ingrediente_id=ing.id, ingrediente_nome=ing.nome, ingrediente_tipo=ing.tipo,
        estoque_item_id=item.id, qtd_p=receita.qtd_p, qtd_m=receita.qtd_m, qtd_g=receita.qtd_g,
    )
