from collections import defaultdict
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..database import get_db
from ..auth import exigir_admin
from ..tempo import hoje_local, inicio_do_dia_em_utc, utc_para_local

# Todas as rotas daqui exigem login de dono/gerente
router = APIRouter(prefix="/gerencial", tags=["Gerencial"], dependencies=[Depends(exigir_admin)])

MAX_DIAS_PERIODO = 366


def _periodo(inicio: Optional[date], fim: Optional[date]) -> tuple[date, date]:
    """Padrão: últimos 30 dias (incluindo hoje)."""
    fim = fim or hoje_local()
    inicio = inicio or fim - timedelta(days=29)
    if inicio > fim:
        raise HTTPException(status_code=422, detail="A data inicial deve ser anterior à final")
    if (fim - inicio).days >= MAX_DIAS_PERIODO:
        raise HTTPException(status_code=422, detail="Período máximo de 1 ano")
    return inicio, fim


# ---------------------------------------------------------------------
# Resumo financeiro (faturamento x despesas)
# ---------------------------------------------------------------------

@router.get("/resumo", response_model=schemas.ResumoFinanceiro)
def resumo_financeiro(
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _periodo(inicio, fim)

    pedidos = (
        db.query(models.Pedido)
        .options(joinedload(models.Pedido.itens))
        .filter(
            models.Pedido.criado_em >= inicio_do_dia_em_utc(inicio),
            models.Pedido.criado_em < inicio_do_dia_em_utc(fim + timedelta(days=1)),
        )
        .all()
    )
    despesas = (
        db.query(models.Despesa)
        .filter(models.Despesa.data >= inicio, models.Despesa.data <= fim)
        .all()
    )

    # Um registro por dia do período, mesmo sem movimento, para o gráfico não "pular" dias
    por_dia = {
        inicio + timedelta(days=i): {"faturamento": 0.0, "despesas": 0.0, "pedidos": 0}
        for i in range((fim - inicio).days + 1)
    }
    itens = defaultdict(lambda: {"quantidade": 0, "receita": 0.0})
    validos = [p for p in pedidos if p.status != models.StatusPedido.cancelado]

    for p in validos:
        dia = por_dia[utc_para_local(p.criado_em).date()]
        dia["faturamento"] += p.total
        dia["pedidos"] += 1
        for item in p.itens:
            itens[item.nome]["quantidade"] += item.quantidade
            itens[item.nome]["receita"] += item.preco_unitario * item.quantidade

    por_categoria = defaultdict(float)
    for d in despesas:
        por_dia[d.data]["despesas"] += d.valor
        por_categoria[d.categoria] += d.valor

    faturamento = round(sum(p.total for p in validos), 2)
    total_despesas = round(sum(d.valor for d in despesas), 2)

    return schemas.ResumoFinanceiro(
        inicio=inicio,
        fim=fim,
        faturamento=faturamento,
        taxas_entrega=round(sum(p.taxa_entrega for p in validos), 2),
        despesas=total_despesas,
        lucro=round(faturamento - total_despesas, 2),
        pedidos=len(validos),
        pedidos_cancelados=len(pedidos) - len(validos),
        ticket_medio=round(faturamento / len(validos), 2) if validos else 0.0,
        pedidos_delivery=sum(p.tipo_entrega == models.TipoEntrega.delivery for p in validos),
        pedidos_retirada=sum(p.tipo_entrega == models.TipoEntrega.retirada for p in validos),
        por_dia=[
            schemas.ResumoDia(
                data=dia,
                faturamento=round(v["faturamento"], 2),
                despesas=round(v["despesas"], 2),
                pedidos=v["pedidos"],
            )
            for dia, v in sorted(por_dia.items())
        ],
        top_itens=sorted(
            (
                schemas.ResumoItem(nome=nome, quantidade=v["quantidade"], receita=round(v["receita"], 2))
                for nome, v in itens.items()
            ),
            key=lambda i: i.receita,
            reverse=True,
        )[:10],
        despesas_por_categoria=sorted(
            (schemas.ResumoCategoria(categoria=c, total=round(t, 2)) for c, t in por_categoria.items()),
            key=lambda c: c.total,
            reverse=True,
        ),
    )


# ---------------------------------------------------------------------
# Despesas (CRUD)
# ---------------------------------------------------------------------

@router.get("/despesas", response_model=List[schemas.DespesaOut])
def listar_despesas(
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    categoria: Optional[models.CategoriaDespesa] = None,
    db: Session = Depends(get_db),
):
    inicio, fim = _periodo(inicio, fim)
    query = db.query(models.Despesa).filter(models.Despesa.data >= inicio, models.Despesa.data <= fim)
    if categoria:
        query = query.filter(models.Despesa.categoria == categoria)
    return query.order_by(models.Despesa.data.desc(), models.Despesa.id.desc()).all()


@router.post("/despesas", response_model=schemas.DespesaOut, status_code=201)
def criar_despesa(
    dados: schemas.DespesaIn,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_admin),
):
    despesa = models.Despesa(
        descricao=dados.descricao,
        categoria=dados.categoria,
        valor=round(dados.valor, 2),
        data=dados.data,
        criado_por_id=usuario.id,
    )
    db.add(despesa)
    db.commit()
    db.refresh(despesa)
    return despesa


@router.put("/despesas/{despesa_id}", response_model=schemas.DespesaOut)
def atualizar_despesa(despesa_id: int, dados: schemas.DespesaIn, db: Session = Depends(get_db)):
    despesa = db.get(models.Despesa, despesa_id)
    if not despesa:
        raise HTTPException(status_code=404, detail="Despesa não encontrada")
    despesa.descricao = dados.descricao
    despesa.categoria = dados.categoria
    despesa.valor = round(dados.valor, 2)
    despesa.data = dados.data
    db.commit()
    db.refresh(despesa)
    return despesa


@router.delete("/despesas/{despesa_id}", status_code=204)
def excluir_despesa(despesa_id: int, db: Session = Depends(get_db)):
    despesa = db.get(models.Despesa, despesa_id)
    if not despesa:
        raise HTTPException(status_code=404, detail="Despesa não encontrada")
    db.delete(despesa)
    db.commit()
