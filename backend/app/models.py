import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Text, Date, DateTime, Time, ForeignKey, Enum
)
from sqlalchemy.orm import relationship

from .database import Base


class CategoriaPizza(str, enum.Enum):
    tradicionais = "tradicionais"
    especiais = "especiais"
    doces = "doces"


class TipoEntrega(str, enum.Enum):
    delivery = "delivery"
    retirada = "retirada"


class StatusPedido(str, enum.Enum):
    pendente = "pendente"
    em_preparo = "em_preparo"
    pronto = "pronto"
    saiu_entrega = "saiu_entrega"  # delivery: está com o entregador
    entregue = "entregue"          # finalizado (entregue ao cliente ou retirado no balcão)
    cancelado = "cancelado"


class FormaPagamento(str, enum.Enum):
    pix = "pix"
    credito = "credito"
    debito = "debito"
    dinheiro = "dinheiro"


class TipoItemPedido(str, enum.Enum):
    cardapio = "cardapio"
    custom = "custom"
    bebida = "bebida"


class Cargo(str, enum.Enum):
    admin = "admin"      # dono/gerente: acesso à cozinha e à área gerencial
    cozinha = "cozinha"  # funcionários: só a tela da cozinha


class CategoriaDespesa(str, enum.Enum):
    ingredientes = "ingredientes"
    bebidas = "bebidas"
    embalagens = "embalagens"
    salarios = "salarios"
    aluguel = "aluguel"
    contas = "contas"          # água, luz, gás, internet
    entregas = "entregas"      # motoboys, combustível
    marketing = "marketing"
    manutencao = "manutencao"
    impostos = "impostos"
    outros = "outros"


# ---------------------------------------------------------------------
# Cardápio
# ---------------------------------------------------------------------

class Pizza(Base):
    __tablename__ = "pizzas"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(60), unique=True, index=True, nullable=False)
    nome = Column(String(80), nullable=False)
    categoria = Column(Enum(CategoriaPizza), nullable=False)
    descricao = Column(String(255), default="")
    cor_hex = Column(String(7), default="#C1391F")  # usado no thumb ilustrativo do front
    preco_p = Column(Float, nullable=False)
    preco_m = Column(Float, nullable=False)
    preco_g = Column(Float, nullable=False)
    ativo = Column(Integer, default=1)  # 1 = disponível no cardápio, 0 = oculto


class Bebida(Base):
    __tablename__ = "bebidas"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(60), unique=True, nullable=True)  # nome da foto: img/bebidas/<slug>.jpg
    nome = Column(String(80), nullable=False)
    descricao = Column(String(255), default="")
    preco = Column(Float, nullable=False)
    ativo = Column(Integer, default=1)


class TipoIngrediente(str, enum.Enum):
    massa = "massa"
    molho = "molho"
    topping = "topping"


class Ingrediente(Base):
    """Opções usadas na tela 'Monte sua pizza' (massa, molho, coberturas)."""
    __tablename__ = "ingredientes"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(60), unique=True, nullable=True)  # nome da foto: img/ingredientes/<slug>.jpg
    nome = Column(String(80), nullable=False)
    tipo = Column(Enum(TipoIngrediente), nullable=False)
    preco_adicional = Column(Float, default=0)
    cor_hex = Column(String(7), default="#FFFBF3")  # cor do "topping" no preview visual
    ativo = Column(Integer, default=1)


class TamanhoPizza(Base):
    """Tamanhos da pizza montada e o preço base de cada um (antes fixos no site)."""
    __tablename__ = "tamanhos_pizza"

    codigo = Column(String(1), primary_key=True)  # P, M, G
    nome = Column(String(30), nullable=False)
    fatias = Column(Integer, nullable=False)
    preco_base = Column(Float, nullable=False)


# ---------------------------------------------------------------------
# Entrega e funcionamento
# ---------------------------------------------------------------------

class BairroEntrega(Base):
    __tablename__ = "bairros_entrega"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(80), unique=True, nullable=False)
    taxa = Column(Float, nullable=False)
    ativo = Column(Integer, default=1)


class Entregador(Base):
    __tablename__ = "entregadores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(80), nullable=False)
    telefone = Column(String(20), nullable=True)  # também é o login na área do entregador
    ativo = Column(Integer, default=1)
    senha_hash = Column(String(255), nullable=True)  # vazio = sem acesso à área do entregador

    @property
    def tem_acesso(self) -> bool:
        return bool(self.senha_hash)


class HorarioFuncionamento(Base):
    __tablename__ = "horarios_funcionamento"

    # autoincrement=False: no MySQL a coluna viraria AUTO_INCREMENT e o dia 0 (segunda) seria trocado
    dia_semana = Column(Integer, primary_key=True, autoincrement=False)  # 0 = segunda ... 6 = domingo
    abre = Column(Time, nullable=False)
    fecha = Column(Time, nullable=False)  # se fecha < abre, o horário passa da meia-noite
    fechado = Column(Integer, default=0)  # 1 = não abre neste dia


class Configuracao(Base):
    """Pares chave/valor da operação (ex.: pedidos pausados pela cozinha)."""
    __tablename__ = "configuracoes"

    chave = Column(String(60), primary_key=True)
    valor = Column(String(255), nullable=True)


# ---------------------------------------------------------------------
# Clientes e pedidos
# ---------------------------------------------------------------------

class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    telefone = Column(String(20), nullable=False)
    endereco = Column(String(255), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)

    pedidos = relationship("Pedido", back_populates="cliente")


class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    tipo_entrega = Column(Enum(TipoEntrega), nullable=False)
    endereco_entrega = Column(String(255), nullable=True)  # obrigatório apenas se delivery
    status = Column(Enum(StatusPedido), default=StatusPedido.pendente, nullable=False)
    subtotal = Column(Float, nullable=False)
    taxa_entrega = Column(Float, default=0)
    total = Column(Float, nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Acompanhamento público: o cliente usa este código (não adivinhável) no link
    codigo_acompanhamento = Column(String(32), unique=True, index=True, nullable=True)

    # Pagamento
    forma_pagamento = Column(Enum(FormaPagamento), nullable=True)
    troco_para = Column(Float, nullable=True)  # dinheiro: valor da nota do cliente
    pago = Column(Integer, default=0, nullable=False)
    pago_em = Column(DateTime, nullable=True)
    # Comprovante do Pix enviado pelo cliente (arquivo salvo em UPLOAD_DIR com nome aleatório)
    comprovante_arquivo = Column(String(80), nullable=True)
    comprovante_enviado_em = Column(DateTime, nullable=True)

    # Entrega
    bairro_id = Column(Integer, ForeignKey("bairros_entrega.id"), nullable=True)
    bairro_nome = Column(String(80), nullable=True)  # cópia: o bairro pode mudar de nome/taxa depois
    entregador_id = Column(Integer, ForeignKey("entregadores.id"), nullable=True)
    saiu_entrega_em = Column(DateTime, nullable=True)
    finalizado_em = Column(DateTime, nullable=True)

    cliente = relationship("Cliente", back_populates="pedidos")
    entregador = relationship("Entregador")
    itens = relationship("PedidoItem", back_populates="pedido", cascade="all, delete-orphan")


class PedidoItem(Base):
    __tablename__ = "pedido_itens"

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False)
    tipo = Column(Enum(TipoItemPedido), nullable=False)
    nome = Column(String(120), nullable=False)
    tamanho = Column(String(10), nullable=True)  # P / M / G, vazio para bebidas
    preco_unitario = Column(Float, nullable=False)
    quantidade = Column(Integer, nullable=False, default=1)
    detalhes = Column(Text, nullable=True)  # texto livre: "Massa integral · Molho branco · Bacon, Catupiry"

    pedido = relationship("Pedido", back_populates="itens")


# ---------------------------------------------------------------------
# Usuários (staff — login para o painel da cozinha)
# ---------------------------------------------------------------------

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    cargo = Column(Enum(Cargo), default=Cargo.cozinha, nullable=False)
    ativo = Column(Integer, default=1)


# ---------------------------------------------------------------------
# Gerencial — despesas lançadas pelo dono
# ---------------------------------------------------------------------

class Despesa(Base):
    __tablename__ = "despesas"

    id = Column(Integer, primary_key=True, index=True)
    descricao = Column(String(160), nullable=False)
    categoria = Column(Enum(CategoriaDespesa), nullable=False)
    valor = Column(Float, nullable=False)
    data = Column(Date, nullable=False, index=True)  # data da despesa no horário local
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------
# Estoque
# ---------------------------------------------------------------------

class UnidadeEstoque(str, enum.Enum):
    un = "un"   # contado em unidades (bebidas, embalagens)
    kg = "kg"   # pesado (farinha, queijos, molhos)


# Limite padrão de alerta quando o item é cadastrado sem um mínimo próprio
MINIMO_PADRAO = {UnidadeEstoque.un: 10.0, UnidadeEstoque.kg: 10.0}


class TipoMovimentacao(str, enum.Enum):
    entrada = "entrada"      # compra / reposição (manual)
    saida = "saida"          # uso na cozinha, perda (manual)
    ajuste = "ajuste"        # correção após contagem (manual)
    pedido = "pedido"        # baixa automática por pedido
    estorno = "estorno"      # devolução automática por pedido cancelado


class EstoqueItem(Base):
    __tablename__ = "estoque_itens"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), unique=True, nullable=False)
    unidade = Column(Enum(UnidadeEstoque), nullable=False)
    quantidade = Column(Float, nullable=False, default=0)
    minimo = Column(Float, nullable=False)  # alerta quando quantidade < minimo
    # Bebida vendida no cardápio: cada unidade pedida baixa 1 deste item
    bebida_id = Column(Integer, ForeignKey("bebidas.id"), unique=True, nullable=True)
    ativo = Column(Integer, default=1)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bebida = relationship("Bebida")


class ConsumoIngrediente(Base):
    """Receita da pizza montada: quanto (em kg) cada ingrediente escolhido pelo
    cliente consome do estoque, por tamanho. Vários ingredientes podem apontar
    para o mesmo item (ex.: massas Tradicional e Fina → Farinha de trigo)."""
    __tablename__ = "consumo_ingredientes"

    ingrediente_id = Column(Integer, ForeignKey("ingredientes.id"), primary_key=True)
    estoque_item_id = Column(Integer, ForeignKey("estoque_itens.id"), nullable=False)
    qtd_p = Column(Float, nullable=False, default=0)
    qtd_m = Column(Float, nullable=False, default=0)
    qtd_g = Column(Float, nullable=False, default=0)

    ingrediente = relationship("Ingrediente")
    estoque_item = relationship("EstoqueItem")


class MovimentacaoEstoque(Base):
    __tablename__ = "estoque_movimentacoes"

    id = Column(Integer, primary_key=True, index=True)
    estoque_item_id = Column(Integer, ForeignKey("estoque_itens.id"), nullable=False, index=True)
    tipo = Column(Enum(TipoMovimentacao), nullable=False)
    quantidade = Column(Float, nullable=False)  # positivo = entrou, negativo = saiu
    saldo = Column(Float, nullable=False)       # quantidade do item logo após a movimentação
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    observacao = Column(String(255), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, index=True)

    estoque_item = relationship("EstoqueItem")
    usuario = relationship("Usuario")
