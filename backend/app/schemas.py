import re
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    CategoriaPizza, TipoEntrega, StatusPedido, TipoItemPedido, TipoIngrediente, Cargo,
    CategoriaDespesa, UnidadeEstoque,
)


# ---------------------------------------------------------------------
# Cardápio
# ---------------------------------------------------------------------

class PizzaOut(BaseModel):
    id: int
    slug: str
    nome: str
    categoria: CategoriaPizza
    descricao: str
    cor_hex: str
    preco_p: float
    preco_m: float
    preco_g: float

    class Config:
        from_attributes = True


class BebidaOut(BaseModel):
    id: int
    nome: str
    descricao: str
    preco: float

    class Config:
        from_attributes = True


class IngredienteOut(BaseModel):
    id: int
    nome: str
    tipo: TipoIngrediente
    preco_adicional: float
    cor_hex: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------

class PedidoItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: TipoItemPedido
    # Identificador do produto no cardápio: slug da pizza ou nome da bebida.
    # Quando presente, o preço é buscado no banco e o preco_unitario enviado é ignorado.
    ref: Optional[str] = Field(default=None, max_length=120)
    nome: str = Field(min_length=1, max_length=120)
    tamanho: Optional[Literal["P", "M", "G"]] = None
    preco_unitario: float = Field(gt=0, le=1000)
    quantidade: int = Field(gt=0, le=50)
    detalhes: Optional[str] = Field(default=None, max_length=500)
    # Pizza montada: nomes da massa, molho e coberturas escolhidos (usados para baixar o estoque)
    ingredientes: Optional[List[str]] = Field(default=None, max_length=30)

    @field_validator("tamanho", mode="before")
    @classmethod
    def tamanho_vazio_vira_none(cls, v):
        return v or None


class PedidoItemOut(BaseModel):
    id: int
    tipo: TipoItemPedido
    nome: str
    tamanho: Optional[str] = None
    preco_unitario: float
    quantidade: int
    detalhes: Optional[str] = None

    class Config:
        from_attributes = True


class PedidoIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    cliente_nome: str = Field(min_length=2, max_length=120)
    cliente_telefone: str = Field(min_length=8, max_length=20)
    tipo_entrega: TipoEntrega
    endereco_entrega: Optional[str] = Field(default=None, max_length=255)
    observacoes: Optional[str] = Field(default=None, max_length=500)
    itens: List[PedidoItemIn] = Field(min_length=1, max_length=50)

    @field_validator("cliente_telefone")
    @classmethod
    def normalizar_telefone(cls, v: str) -> str:
        # guarda só os dígitos: "(11) 98765-4321" e "11987654321" viram o mesmo cliente
        digitos = re.sub(r"\D", "", v)
        if not 10 <= len(digitos) <= 13:
            raise ValueError("Telefone inválido — informe DDD + número")
        return digitos

    @model_validator(mode="after")
    def validar_endereco(self):
        if self.tipo_entrega == TipoEntrega.delivery and not self.endereco_entrega:
            raise ValueError("Endereço de entrega é obrigatório para pedidos delivery")
        if self.tipo_entrega == TipoEntrega.retirada:
            self.endereco_entrega = None
        return self


class PedidoOut(BaseModel):
    id: int
    status: StatusPedido
    tipo_entrega: TipoEntrega
    endereco_entrega: Optional[str]
    subtotal: float
    taxa_entrega: float
    total: float
    observacoes: Optional[str]
    criado_em: datetime
    atualizado_em: Optional[datetime] = None
    itens: List[PedidoItemOut]
    cliente_nome: Optional[str] = None
    cliente_telefone: Optional[str] = None

    class Config:
        from_attributes = True


class StatusUpdateIn(BaseModel):
    status: StatusPedido


# ---------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------

class LoginIn(BaseModel):
    email: str
    senha: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nome: str
    cargo: Cargo


class UsuarioOut(BaseModel):
    id: int
    nome: str
    email: str
    cargo: Cargo

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------
# Gerencial
# ---------------------------------------------------------------------

class DespesaIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    descricao: str = Field(min_length=2, max_length=160)
    categoria: CategoriaDespesa
    valor: float = Field(gt=0, le=1_000_000)
    data: date


class DespesaOut(DespesaIn):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True


class ResumoDia(BaseModel):
    data: date
    faturamento: float
    despesas: float
    pedidos: int


class ResumoItem(BaseModel):
    nome: str
    quantidade: int
    receita: float


class ResumoCategoria(BaseModel):
    categoria: CategoriaDespesa
    total: float


class ResumoFinanceiro(BaseModel):
    inicio: date
    fim: date
    faturamento: float        # soma dos pedidos não cancelados
    taxas_entrega: float      # parte do faturamento que veio de taxa de entrega
    despesas: float
    lucro: float
    pedidos: int
    pedidos_cancelados: int
    ticket_medio: float
    pedidos_delivery: int
    pedidos_retirada: int
    por_dia: List[ResumoDia]
    top_itens: List[ResumoItem]
    despesas_por_categoria: List[ResumoCategoria]


# ---------------------------------------------------------------------
# Estoque
# ---------------------------------------------------------------------

class EstoqueItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(min_length=2, max_length=120)
    unidade: UnidadeEstoque
    minimo: Optional[float] = Field(default=None, ge=0, le=100_000)  # vazio = padrão (20 un / 10 kg)
    bebida_id: Optional[int] = None


class EstoqueItemCriarIn(EstoqueItemIn):
    quantidade: float = Field(default=0, ge=0, le=100_000)


class EstoqueItemOut(BaseModel):
    id: int
    nome: str
    unidade: UnidadeEstoque
    quantidade: float
    minimo: float
    status: Literal["ok", "baixo", "zerado"]
    bebida_id: Optional[int] = None
    bebida_nome: Optional[str] = None
    atualizado_em: Optional[datetime] = None


class MovimentarIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: Literal["entrada", "saida", "ajuste"]
    # entrada/saída: quanto entrou ou saiu; ajuste: a nova contagem total
    quantidade: float = Field(ge=0, le=100_000)
    observacao: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def quantidade_positiva(self):
        if self.tipo != "ajuste" and self.quantidade <= 0:
            raise ValueError("Informe uma quantidade maior que zero")
        return self


class MovimentacaoOut(BaseModel):
    id: int
    estoque_item_id: int
    item_nome: str
    unidade: UnidadeEstoque
    tipo: str
    quantidade: float
    saldo: float
    pedido_id: Optional[int] = None
    usuario_nome: Optional[str] = None
    observacao: Optional[str] = None
    criado_em: datetime


class ConsumoIn(BaseModel):
    estoque_item_id: Optional[int] = None  # None = ingrediente não baixa estoque
    qtd_p: float = Field(default=0, ge=0, le=10)
    qtd_m: float = Field(default=0, ge=0, le=10)
    qtd_g: float = Field(default=0, ge=0, le=10)


class ConsumoOut(ConsumoIn):
    ingrediente_id: int
    ingrediente_nome: str
    ingrediente_tipo: TipoIngrediente
