"""Regras de estoque: saldo, alertas, baixa automática por pedido e estorno."""
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models

CASAS = 3  # kg com precisão de grama


def status_item(item: models.EstoqueItem) -> str:
    """ok | baixo (abaixo do mínimo) | zerado (sem estoque)."""
    if item.quantidade <= 0:
        return "zerado"
    if item.quantidade < item.minimo:
        return "baixo"
    return "ok"


def serializar_item(item: models.EstoqueItem) -> dict:
    return {
        "id": item.id,
        "nome": item.nome,
        "unidade": item.unidade.value,
        "quantidade": item.quantidade,
        "minimo": item.minimo,
        "status": status_item(item),
        "bebida_id": item.bebida_id,
        "bebida_nome": item.bebida.nome if item.bebida else None,
        "atualizado_em": item.atualizado_em.isoformat() if item.atualizado_em else None,
    }


def itens_em_alerta(db: Session) -> List[models.EstoqueItem]:
    return (
        db.query(models.EstoqueItem)
        .filter(models.EstoqueItem.ativo == 1, models.EstoqueItem.quantidade < models.EstoqueItem.minimo)
        .order_by(models.EstoqueItem.quantidade / models.EstoqueItem.minimo)
        .all()
    )


def evento_estoque(db: Session) -> dict:
    """Mensagem de WebSocket enviada sempre que o estoque muda."""
    return {"evento": "estoque_atualizado", "alertas": [serializar_item(i) for i in itens_em_alerta(db)]}


def movimentar(
    db: Session,
    item: models.EstoqueItem,
    delta: float,
    tipo: models.TipoMovimentacao,
    usuario_id: Optional[int] = None,
    pedido_id: Optional[int] = None,
    observacao: Optional[str] = None,
) -> models.MovimentacaoEstoque:
    """Aplica a variação no saldo e registra o histórico (não faz commit).

    O saldo pode ficar negativo: a venda nunca é bloqueada por estoque, e o
    número negativo mostra que a contagem precisa ser corrigida.
    """
    item.quantidade = round(item.quantidade + delta, CASAS)
    mov = models.MovimentacaoEstoque(
        estoque_item=item,
        tipo=tipo,
        quantidade=round(delta, CASAS),
        saldo=item.quantidade,
        pedido_id=pedido_id,
        usuario_id=usuario_id,
        observacao=observacao,
    )
    db.add(mov)
    return mov


# ---------------------------------------------------------------------
# Baixa automática por pedido
# ---------------------------------------------------------------------

def consumo_do_pedido(db: Session, itens: Iterable[models.PedidoItem], ingredientes_custom: Dict[int, List[str]]) -> Dict[int, float]:
    """Calcula quanto cada item de estoque deve baixar para este pedido.

    - Bebidas: 1 unidade do item ligado à bebida por unidade vendida.
    - Pizza montada: soma o consumo (kg por tamanho) de massa, molho e coberturas.
    - Pizzas do cardápio: não baixam automaticamente (a cozinha registra o uso manualmente).

    ingredientes_custom: índice do item no pedido → nomes escolhidos pelo cliente.
    """
    consumo: Dict[int, float] = defaultdict(float)
    itens = list(itens)

    nomes_bebidas = {i.nome for i in itens if i.tipo == models.TipoItemPedido.bebida}
    if nomes_bebidas:
        estoque_por_bebida = {
            e.bebida.nome: e
            for e in db.query(models.EstoqueItem)
            .join(models.Bebida, models.EstoqueItem.bebida_id == models.Bebida.id)
            .filter(models.EstoqueItem.ativo == 1, models.Bebida.nome.in_(nomes_bebidas))
        }
        for i in itens:
            if i.tipo == models.TipoItemPedido.bebida and i.nome in estoque_por_bebida:
                consumo[estoque_por_bebida[i.nome].id] += i.quantidade

    nomes_ingredientes = {n.lower() for nomes in ingredientes_custom.values() for n in nomes}
    if nomes_ingredientes:
        receitas = {
            c.ingrediente.nome.lower(): c
            for c in db.query(models.ConsumoIngrediente)
            .join(models.Ingrediente)
            .join(models.EstoqueItem)
            .filter(models.EstoqueItem.ativo == 1, func.lower(models.Ingrediente.nome).in_(nomes_ingredientes))
        }
        for idx, nomes in ingredientes_custom.items():
            pizza = itens[idx]
            for nome in {n.lower() for n in nomes}:  # ingrediente repetido conta uma vez
                receita = receitas.get(nome)
                if not receita:
                    continue
                por_pizza = {"P": receita.qtd_p, "M": receita.qtd_m, "G": receita.qtd_g}.get(pizza.tamanho or "M", 0)
                consumo[receita.estoque_item_id] += por_pizza * pizza.quantidade

    return {k: round(v, CASAS) for k, v in consumo.items() if v > 0}


def baixar_pedido(db: Session, pedido: models.Pedido, consumo: Dict[int, float]) -> bool:
    if not consumo:
        return False
    itens = db.query(models.EstoqueItem).filter(models.EstoqueItem.id.in_(consumo.keys())).all()
    for item in itens:
        movimentar(db, item, -consumo[item.id], models.TipoMovimentacao.pedido,
                   pedido_id=pedido.id, observacao=f"Pedido #{pedido.id}")
    return True


def _saldo_do_pedido(db: Session, pedido_id: int, tipos: List[models.TipoMovimentacao]) -> Dict[int, float]:
    linhas = (
        db.query(models.MovimentacaoEstoque.estoque_item_id, func.sum(models.MovimentacaoEstoque.quantidade))
        .filter(models.MovimentacaoEstoque.pedido_id == pedido_id, models.MovimentacaoEstoque.tipo.in_(tipos))
        .group_by(models.MovimentacaoEstoque.estoque_item_id)
        .all()
    )
    return {item_id: round(total or 0, CASAS) for item_id, total in linhas}


def ajustar_por_mudanca_de_status(
    db: Session, pedido: models.Pedido, status_anterior: models.StatusPedido, usuario_id: Optional[int]
) -> bool:
    """Cancelou → devolve ao estoque o que o pedido baixou.
    Descancelou (voltou de cancelado) → baixa de novo. Retorna True se mexeu no estoque."""
    cancelado = models.StatusPedido.cancelado
    if status_anterior != cancelado and pedido.status == cancelado:
        # saldo atual do pedido (baixas + estornos anteriores); devolve o que ainda está baixado
        saldo = _saldo_do_pedido(db, pedido.id, [models.TipoMovimentacao.pedido, models.TipoMovimentacao.estorno])
        acao, tipo, texto = -1, models.TipoMovimentacao.estorno, "Estorno: pedido #{} cancelado"
    elif status_anterior == cancelado and pedido.status != cancelado:
        # refaz as baixas originais do pedido
        originais = _saldo_do_pedido(db, pedido.id, [models.TipoMovimentacao.pedido])
        vezes = {}
        for mov in db.query(models.MovimentacaoEstoque).filter(
            models.MovimentacaoEstoque.pedido_id == pedido.id,
            models.MovimentacaoEstoque.tipo == models.TipoMovimentacao.pedido,
        ):
            vezes[mov.estoque_item_id] = vezes.get(mov.estoque_item_id, 0) + 1
        saldo = {k: v / vezes[k] for k, v in originais.items()}  # valor de uma baixa
        acao, tipo, texto = 1, models.TipoMovimentacao.pedido, "Pedido #{} reaberto"
    else:
        return False

    mudou = False
    for item_id, qtd in saldo.items():
        if abs(qtd) < 10 ** -CASAS:
            continue
        item = db.get(models.EstoqueItem, item_id)
        movimentar(db, item, qtd * acao, tipo, usuario_id=usuario_id,
                   pedido_id=pedido.id, observacao=texto.format(pedido.id))
        mudou = True
    return mudou
