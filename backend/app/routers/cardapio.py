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
