"""Configurações do dono: cardápio e preços, tamanhos, bairros, entregadores e horários."""
import re
from typing import List, Type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import exigir_admin, hash_senha
from ..database import get_db
from ..loja_service import status_loja
from ..pix_service import ChavePixInvalida, ler_config, salvar_config

router = APIRouter(prefix="/gerencial/config", tags=["Configurações"], dependencies=[Depends(exigir_admin)])


def _salvar(db: Session, obj, mensagem_duplicado: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=mensagem_duplicado)
    db.refresh(obj)
    return obj


def _obter(db: Session, modelo: Type, chave, nome: str):
    obj = db.get(modelo, chave)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{nome} não encontrado")
    return obj


# ---------------------------------------------------------------------
# Cardápio
# ---------------------------------------------------------------------

@router.get("/pizzas", response_model=List[schemas.PizzaAdmin])
def listar_pizzas(db: Session = Depends(get_db)):
    return db.query(models.Pizza).order_by(models.Pizza.id).all()


@router.post("/pizzas", response_model=schemas.PizzaAdmin, status_code=201)
def criar_pizza(dados: schemas.PizzaAdmin, db: Session = Depends(get_db)):
    pizza = models.Pizza(**dados.model_dump(exclude={"id"}))
    db.add(pizza)
    return _salvar(db, pizza, "Já existe uma pizza com esse identificador (slug)")


@router.put("/pizzas/{pizza_id}", response_model=schemas.PizzaAdmin)
def atualizar_pizza(pizza_id: int, dados: schemas.PizzaAdmin, db: Session = Depends(get_db)):
    pizza = _obter(db, models.Pizza, pizza_id, "Pizza")
    for campo, valor in dados.model_dump(exclude={"id"}).items():
        setattr(pizza, campo, valor)
    return _salvar(db, pizza, "Já existe uma pizza com esse identificador (slug)")


@router.get("/bebidas", response_model=List[schemas.BebidaAdmin])
def listar_bebidas(db: Session = Depends(get_db)):
    return db.query(models.Bebida).order_by(models.Bebida.id).all()


@router.post("/bebidas", response_model=schemas.BebidaAdmin, status_code=201)
def criar_bebida(dados: schemas.BebidaAdmin, db: Session = Depends(get_db)):
    bebida = models.Bebida(**dados.model_dump(exclude={"id"}))
    db.add(bebida)
    return _salvar(db, bebida, "Já existe uma bebida com esse identificador (slug)")


@router.put("/bebidas/{bebida_id}", response_model=schemas.BebidaAdmin)
def atualizar_bebida(bebida_id: int, dados: schemas.BebidaAdmin, db: Session = Depends(get_db)):
    bebida = _obter(db, models.Bebida, bebida_id, "Bebida")
    for campo, valor in dados.model_dump(exclude={"id"}).items():
        setattr(bebida, campo, valor)
    return _salvar(db, bebida, "Já existe uma bebida com esse identificador (slug)")


@router.get("/ingredientes", response_model=List[schemas.IngredienteAdmin])
def listar_ingredientes(db: Session = Depends(get_db)):
    return db.query(models.Ingrediente).order_by(models.Ingrediente.id).all()


@router.put("/ingredientes/{ingrediente_id}", response_model=schemas.IngredienteAdmin)
def atualizar_ingrediente(ingrediente_id: int, dados: schemas.IngredientePrecoIn, db: Session = Depends(get_db)):
    ing = _obter(db, models.Ingrediente, ingrediente_id, "Ingrediente")
    if not dados.ativo and ing.tipo != models.TipoIngrediente.topping:
        restantes = (
            db.query(models.Ingrediente)
            .filter(models.Ingrediente.tipo == ing.tipo, models.Ingrediente.ativo == 1, models.Ingrediente.id != ing.id)
            .count()
        )
        if not restantes:
            raise HTTPException(status_code=422, detail=f"É preciso manter ao menos uma opção de {ing.tipo.value} ativa")
    ing.preco_adicional = dados.preco_adicional
    ing.ativo = dados.ativo
    return _salvar(db, ing, "Não foi possível salvar")


@router.get("/tamanhos", response_model=List[schemas.TamanhoOut])
def listar_tamanhos(db: Session = Depends(get_db)):
    return db.query(models.TamanhoPizza).order_by(models.TamanhoPizza.preco_base).all()


@router.put("/tamanhos/{codigo}", response_model=schemas.TamanhoOut)
def atualizar_tamanho(codigo: str, dados: schemas.TamanhoIn, db: Session = Depends(get_db)):
    tamanho = _obter(db, models.TamanhoPizza, codigo.upper(), "Tamanho")
    tamanho.fatias = dados.fatias
    tamanho.preco_base = dados.preco_base
    return _salvar(db, tamanho, "Não foi possível salvar")


# ---------------------------------------------------------------------
# Entrega
# ---------------------------------------------------------------------

@router.get("/bairros", response_model=List[schemas.BairroOut])
def listar_bairros(db: Session = Depends(get_db)):
    return db.query(models.BairroEntrega).order_by(models.BairroEntrega.nome).all()


@router.post("/bairros", response_model=schemas.BairroOut, status_code=201)
def criar_bairro(dados: schemas.BairroIn, db: Session = Depends(get_db)):
    bairro = models.BairroEntrega(**dados.model_dump())
    db.add(bairro)
    return _salvar(db, bairro, "Esse bairro já está cadastrado")


@router.put("/bairros/{bairro_id}", response_model=schemas.BairroOut)
def atualizar_bairro(bairro_id: int, dados: schemas.BairroIn, db: Session = Depends(get_db)):
    bairro = _obter(db, models.BairroEntrega, bairro_id, "Bairro")
    for campo, valor in dados.model_dump().items():
        setattr(bairro, campo, valor)
    return _salvar(db, bairro, "Esse bairro já está cadastrado")


@router.get("/entregadores", response_model=List[schemas.EntregadorOut])
def listar_entregadores(db: Session = Depends(get_db)):
    return db.query(models.Entregador).order_by(models.Entregador.nome).all()


def _aplicar_entregador(db: Session, entregador: models.Entregador, dados: schemas.EntregadorIn):
    """Dados do entregador + acesso à área do entregador (login = celular, senha definida pelo dono)."""
    entregador.nome = dados.nome
    entregador.telefone = dados.telefone or None
    entregador.ativo = dados.ativo
    if dados.remover_acesso:
        entregador.senha_hash = None
    elif dados.senha:
        entregador.senha_hash = hash_senha(dados.senha)
    if entregador.senha_hash:
        digitos = re.sub(r"\D", "", entregador.telefone or "")
        if len(digitos) < 10:
            raise HTTPException(status_code=422, detail="Para liberar o acesso, informe o celular do entregador (é o login dele)")
        outro = next((e for e in db.query(models.Entregador)
                      if e.id != entregador.id and e.senha_hash and re.sub(r"\D", "", e.telefone or "") == digitos), None)
        if outro:
            raise HTTPException(status_code=409, detail=f"Esse celular já é o login de {outro.nome}")


@router.post("/entregadores", response_model=schemas.EntregadorOut, status_code=201)
def criar_entregador(dados: schemas.EntregadorIn, db: Session = Depends(get_db)):
    entregador = models.Entregador()
    _aplicar_entregador(db, entregador, dados)
    db.add(entregador)
    return _salvar(db, entregador, "Não foi possível salvar")


@router.put("/entregadores/{entregador_id}", response_model=schemas.EntregadorOut)
def atualizar_entregador(entregador_id: int, dados: schemas.EntregadorIn, db: Session = Depends(get_db)):
    entregador = _obter(db, models.Entregador, entregador_id, "Entregador")
    _aplicar_entregador(db, entregador, dados)
    return _salvar(db, entregador, "Não foi possível salvar")


# ---------------------------------------------------------------------
# Horário de funcionamento
# ---------------------------------------------------------------------

@router.get("/horarios", response_model=List[schemas.HorarioDia])
def listar_horarios(db: Session = Depends(get_db)):
    return db.query(models.HorarioFuncionamento).order_by(models.HorarioFuncionamento.dia_semana).all()


@router.put("/horarios", response_model=schemas.LojaStatusOut)
def salvar_horarios(dados: List[schemas.HorarioDia], db: Session = Depends(get_db)):
    """Recebe os 7 dias da semana de uma vez e devolve o status da loja já com o novo horário."""
    if sorted(d.dia_semana for d in dados) != list(range(7)):
        raise HTTPException(status_code=422, detail="Envie os 7 dias da semana (0 = segunda … 6 = domingo)")
    for d in dados:
        if not d.fechado and d.abre == d.fecha:
            raise HTTPException(status_code=422, detail="O horário de abertura e o de fechamento não podem ser iguais")
        h = db.get(models.HorarioFuncionamento, d.dia_semana) or models.HorarioFuncionamento(dia_semana=d.dia_semana)
        h.abre, h.fecha, h.fechado = d.abre, d.fecha, d.fechado
        db.add(h)
    db.commit()
    return status_loja(db)


# ---------------------------------------------------------------------
# Pix
# ---------------------------------------------------------------------

@router.get("/pix", response_model=schemas.PixConfig)
def obter_pix(db: Session = Depends(get_db)):
    cfg = ler_config(db)
    return schemas.PixConfig(tipo=cfg["tipo"] or "telefone", chave=cfg["chave"], nome=cfg["nome"], cidade=cfg["cidade"])


@router.put("/pix", response_model=schemas.PixConfig)
def salvar_pix(dados: schemas.PixConfig, db: Session = Depends(get_db)):
    if dados.chave and (len(dados.nome) < 2 or len(dados.cidade) < 2):
        raise HTTPException(status_code=422, detail="Informe o nome de quem recebe e a cidade (aparecem no app do banco)")
    try:
        salvar_config(db, dados.tipo, dados.chave, dados.nome, dados.cidade)
    except ChavePixInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return obter_pix(db)
