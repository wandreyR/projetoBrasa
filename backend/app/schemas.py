import re
from datetime import date, datetime, time
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    CategoriaPizza, TipoEntrega, StatusPedido, TipoItemPedido, TipoIngrediente, Cargo,
    CategoriaDespesa, UnidadeEstoque, FormaPagamento,
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
    slug: Optional[str] = None
    nome: str
    descricao: str
    preco: float

    class Config:
        from_attributes = True


class IngredienteOut(BaseModel):
    id: int
    slug: Optional[str] = None
    nome: str
    tipo: TipoIngrediente
    preco_adicional: float
    cor_hex: str

    class Config:
        from_attributes = True


class TamanhoOut(BaseModel):
    codigo: str
    nome: str
    fatias: int
    preco_base: float

    class Config:
        from_attributes = True


class MontagemOut(BaseModel):
    """Tudo que a tela "Monte a sua" precisa: tamanhos com preço base e os ingredientes."""
    tamanhos: List[TamanhoOut]
    massas: List[IngredienteOut]
    molhos: List[IngredienteOut]
    coberturas: List[IngredienteOut]
    max_porcoes: int


class LojaStatusOut(BaseModel):
    aberto: bool
    pausado: bool
    em_horario: bool
    mensagem: str


class PixPublicoOut(BaseModel):
    disponivel: bool
    chave: str = ""
    nome: str = ""


class PixPedidoOut(BaseModel):
    chave: str
    nome: str
    valor: float
    copia_e_cola: str
    qr_svg: str


class PixConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: Literal["cpf", "cnpj", "telefone", "email", "aleatoria"] = "telefone"
    chave: str = Field(default="", max_length=77)   # vazio = Pix desligado no site
    nome: str = Field(default="", max_length=60)    # nome de quem recebe (aparece no app do banco)
    cidade: str = Field(default="", max_length=40)


class BairroOut(BaseModel):
    id: int
    nome: str
    taxa: float
    ativo: int = 1

    class Config:
        from_attributes = True


class DisponibilidadeOut(BaseModel):
    bebidas_esgotadas: List[str]
    ingredientes_esgotados: dict  # {"P": [nomes], "M": [...], "G": [...]}


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
    preco_unitario: Optional[float] = Field(default=None, ge=0, le=1000)  # ignorado: o preço vem do banco
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
    forma_pagamento: FormaPagamento
    troco_para: Optional[float] = Field(default=None, ge=0, le=10_000)  # dinheiro: valor da nota
    bairro_id: Optional[int] = None  # obrigatório para delivery: define a taxa de entrega

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
        if self.tipo_entrega == TipoEntrega.delivery:
            if not self.endereco_entrega:
                raise ValueError("Endereço de entrega é obrigatório para pedidos delivery")
            if not self.bairro_id:
                raise ValueError("Escolha o bairro de entrega")
        if self.tipo_entrega == TipoEntrega.retirada:
            self.endereco_entrega = None
            self.bairro_id = None
        if self.forma_pagamento != FormaPagamento.dinheiro:
            self.troco_para = None
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
    codigo_acompanhamento: Optional[str] = None
    forma_pagamento: Optional[FormaPagamento] = None
    troco_para: Optional[float] = None
    pago: bool = False
    bairro_nome: Optional[str] = None
    entregador_id: Optional[int] = None
    entregador_nome: Optional[str] = None
    saiu_entrega_em: Optional[datetime] = None
    finalizado_em: Optional[datetime] = None
    comprovante_enviado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcompanhamentoItemOut(BaseModel):
    nome: str
    tamanho: Optional[str] = None
    quantidade: int
    detalhes: Optional[str] = None


class AcompanhamentoOut(BaseModel):
    """Visão pública do pedido (link do cliente): sem telefone nem endereço completo."""
    id: int
    status: StatusPedido
    tipo_entrega: TipoEntrega
    cliente_primeiro_nome: str
    bairro_nome: Optional[str] = None
    entregador_nome: Optional[str] = None
    forma_pagamento: Optional[FormaPagamento] = None
    troco_para: Optional[float] = None
    pago: bool
    subtotal: float
    taxa_entrega: float
    total: float
    criado_em: datetime
    atualizado_em: Optional[datetime] = None
    saiu_entrega_em: Optional[datetime] = None
    finalizado_em: Optional[datetime] = None
    comprovante_enviado: bool = False
    itens: List[AcompanhamentoItemOut]


class StatusUpdateIn(BaseModel):
    status: StatusPedido
    entregador_id: Optional[int] = None  # ao mudar para saiu_entrega


class PagamentoIn(BaseModel):
    pago: bool


class PausaIn(BaseModel):
    pausado: bool


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
    a_receber: float = 0.0  # pedidos não cancelados ainda não marcados como pagos
    por_pagamento: List["ResumoPagamento"] = []
    por_entregador: List["ResumoEntregador"] = []


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


class ResumoPagamento(BaseModel):
    forma: str  # pix | credito | debito | dinheiro | nao_informado
    pedidos: int
    total: float


class ResumoEntregador(BaseModel):
    entregador_id: Optional[int] = None
    nome: str
    entregas: int
    taxas: float


# ---------------------------------------------------------------------
# Configurações (dono): cardápio, entrega e horários
# ---------------------------------------------------------------------

SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class PizzaAdmin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)

    id: Optional[int] = None
    slug: str = Field(min_length=2, max_length=60, pattern=SLUG)
    nome: str = Field(min_length=2, max_length=80)
    categoria: CategoriaPizza
    descricao: str = Field(default="", max_length=255)
    preco_p: float = Field(gt=0, le=1000)
    preco_m: float = Field(gt=0, le=1000)
    preco_g: float = Field(gt=0, le=1000)
    ativo: int = Field(default=1, ge=0, le=1)


class BebidaAdmin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)

    id: Optional[int] = None
    slug: str = Field(min_length=2, max_length=60, pattern=SLUG)
    nome: str = Field(min_length=2, max_length=80)
    descricao: str = Field(default="", max_length=255)
    preco: float = Field(gt=0, le=1000)
    ativo: int = Field(default=1, ge=0, le=1)


class IngredienteAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: Optional[str] = None
    nome: str
    tipo: TipoIngrediente
    preco_adicional: float = Field(ge=0, le=100)
    ativo: int = Field(default=1, ge=0, le=1)


class IngredientePrecoIn(BaseModel):
    preco_adicional: float = Field(ge=0, le=100)
    ativo: int = Field(default=1, ge=0, le=1)


class TamanhoIn(BaseModel):
    fatias: int = Field(ge=1, le=24)
    preco_base: float = Field(gt=0, le=1000)


class BairroIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(min_length=2, max_length=80)
    taxa: float = Field(ge=0, le=200)
    ativo: int = Field(default=1, ge=0, le=1)


class EntregadorIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(min_length=2, max_length=80)
    telefone: Optional[str] = Field(default=None, max_length=20)
    ativo: int = Field(default=1, ge=0, le=1)
    # senha da área do entregador: vazio = mantém a atual; "remover_acesso" tira o acesso
    senha: Optional[str] = Field(default=None, max_length=64)
    remover_acesso: bool = False

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v):
        if v and len(v) < 4:
            raise ValueError("A senha do entregador precisa ter pelo menos 4 caracteres")
        return v or None


class EntregadorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    telefone: Optional[str] = None
    ativo: int = 1
    tem_acesso: bool = False  # a senha nunca volta na resposta


class LoginEntregadorIn(BaseModel):
    telefone: str = Field(min_length=8, max_length=20)
    senha: str = Field(min_length=1, max_length=64)


class TokenEntregadorOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nome: str
    cargo: str = "entregador"


class EntregaOut(BaseModel):
    """O que o entregador precisa para levar o pedido (só pedidos de entrega)."""
    id: int
    status: StatusPedido
    cliente_nome: str
    cliente_telefone: str
    endereco_entrega: Optional[str] = None
    bairro_nome: Optional[str] = None
    observacoes: Optional[str] = None
    itens: List[AcompanhamentoItemOut]
    total: float
    taxa_entrega: float
    forma_pagamento: Optional[FormaPagamento] = None
    troco_para: Optional[float] = None
    pago: bool
    criado_em: datetime
    atualizado_em: Optional[datetime] = None
    saiu_entrega_em: Optional[datetime] = None
    minha: bool = False


class NaCozinhaOut(BaseModel):
    id: int
    status: StatusPedido
    bairro_nome: Optional[str] = None
    criado_em: datetime


class PainelEntregadorOut(BaseModel):
    entregador_nome: str
    prontos: List[EntregaOut]       # prontos esperando entregador
    minhas: List[EntregaOut]        # saíram comigo e ainda não foram entregues
    na_cozinha: List[NaCozinhaOut]  # entregas que vão ficar prontas em breve
    entregues_hoje: int
    taxas_hoje: float


class EntregueIn(BaseModel):
    recebi_pagamento: bool = False  # dinheiro/cartão recebido na porta → marca como pago


class HorarioDia(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dia_semana: int = Field(ge=0, le=6)
    abre: time
    fecha: time
    fechado: int = Field(default=0, ge=0, le=1)


ResumoFinanceiro.model_rebuild()
