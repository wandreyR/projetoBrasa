from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/cardapio", tags=["Cardápio"])


@router.get("/pizzas", response_model=List[schemas.PizzaOut])
def listar_pizzas(categoria: Optional[models.CategoriaPizza] = None, db: Session = Depends(get_db)):
    query = db.query(models.Pizza).filter(models.Pizza.ativo == 1)
    if categoria:
        query = query.filter(models.Pizza.categoria == categoria)
    return query.order_by(models.Pizza.nome).all()


@router.get("/bebidas", response_model=List[schemas.BebidaOut])
def listar_bebidas(db: Session = Depends(get_db)):
    return db.query(models.Bebida).filter(models.Bebida.ativo == 1).order_by(models.Bebida.nome).all()


@router.get("/ingredientes", response_model=List[schemas.IngredienteOut])
def listar_ingredientes(
    tipo: Optional[models.TipoIngrediente] = None, db: Session = Depends(get_db)
):
    """Usado pela tela 'Monte sua pizza': massas, molhos e coberturas disponíveis."""
    query = db.query(models.Ingrediente).filter(models.Ingrediente.ativo == 1)
    if tipo:
        query = query.filter(models.Ingrediente.tipo == tipo)
    return query.order_by(models.Ingrediente.nome).all()


@router.get("/disponibilidade", response_model=schemas.DisponibilidadeOut)
def disponibilidade(db: Session = Depends(get_db)):
    """O que está esgotado agora, para o site desabilitar antes do cliente tentar comprar.

    - bebidas_esgotadas: bebidas cujo item de estoque não tem 1 unidade
    - ingredientes_esgotados: por tamanho, ingredientes da pizza montada sem saldo para 1 pizza
    Itens sem controle de estoque (sem vínculo) são sempre considerados disponíveis.
    """
    bebidas = (
        db.query(models.Bebida.nome)
        .join(models.EstoqueItem, models.EstoqueItem.bebida_id == models.Bebida.id)
        .filter(models.EstoqueItem.ativo == 1, models.EstoqueItem.quantidade < 1)
        .all()
    )
    esgotados = {"P": [], "M": [], "G": []}
    receitas = (
        db.query(models.ConsumoIngrediente)
        .join(models.EstoqueItem)
        .filter(models.EstoqueItem.ativo == 1)
        .all()
    )
    for r in receitas:
        saldo = r.estoque_item.quantidade
        for tamanho, qtd in (("P", r.qtd_p), ("M", r.qtd_m), ("G", r.qtd_g)):
            if qtd > 0 and saldo + 0.0005 < qtd:
                esgotados[tamanho].append(r.ingrediente.nome)
    return schemas.DisponibilidadeOut(
        bebidas_esgotadas=[b.nome for b in bebidas],
        ingredientes_esgotados=esgotados,
    )
