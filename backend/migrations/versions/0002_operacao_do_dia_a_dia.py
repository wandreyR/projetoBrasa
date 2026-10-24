"""operacao do dia a dia: cardápio no banco, pagamento, entrega, horários e acompanhamento

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""
import secrets

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

STATUS_ANTIGO = ('pendente', 'em_preparo', 'pronto', 'entregue', 'cancelado')
STATUS_NOVO = ('pendente', 'em_preparo', 'pronto', 'saiu_entrega', 'entregue', 'cancelado')

# slug = nome do arquivo da foto (img/bebidas/<slug>.jpg, img/ingredientes/<slug>.jpg)
SLUGS_BEBIDAS = {
    "Coca-Cola 350ml": "coca-cola", "Guaraná 350ml": "guarana",
    "Suco Natural": "suco-natural", "Água Mineral": "agua",
}
SLUGS_INGREDIENTES = {
    "Tradicional": "tradicional", "Fina": "fina", "Integral": "integral",
    "Molho de tomate": "tomate", "Branco (alho e azeite)": "branco", "Barbecue": "barbecue",
    "Mussarela": "mussarela", "Calabresa": "calabresa", "Frango": "frango", "Presunto": "presunto",
    "Bacon": "bacon", "Champignon": "champignon", "Cebola roxa": "cebola", "Pimentão": "pimentao",
    "Azeitona": "azeitona", "Milho": "milho", "Catupiry": "catupiry", "Gorgonzola": "gorgonzola",
    "Rúcula": "rucula", "Tomate seco": "tomate-seco", "Palmito": "palmito",
}


def upgrade() -> None:
    op.create_table(
        'bairros_entrega',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('taxa', sa.Float(), nullable=False),
        sa.Column('ativo', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome', name='uq_bairros_entrega_nome'),
    )
    op.create_index('ix_bairros_entrega_id', 'bairros_entrega', ['id'])

    op.create_table(
        'configuracoes',
        sa.Column('chave', sa.String(length=60), nullable=False),
        sa.Column('valor', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('chave'),
    )
    op.create_table(
        'entregadores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('ativo', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_entregadores_id', 'entregadores', ['id'])

    op.create_table(
        'horarios_funcionamento',
        sa.Column('dia_semana', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('abre', sa.Time(), nullable=False),
        sa.Column('fecha', sa.Time(), nullable=False),
        sa.Column('fechado', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('dia_semana'),
    )
    op.create_table(
        'tamanhos_pizza',
        sa.Column('codigo', sa.String(length=1), nullable=False),
        sa.Column('nome', sa.String(length=30), nullable=False),
        sa.Column('fatias', sa.Integer(), nullable=False),
        sa.Column('preco_base', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('codigo'),
    )

    with op.batch_alter_table('bebidas') as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(length=60), nullable=True))
        batch_op.create_unique_constraint('uq_bebidas_slug', ['slug'])

    with op.batch_alter_table('ingredientes') as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(length=60), nullable=True))
        batch_op.create_unique_constraint('uq_ingredientes_slug', ['slug'])

    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.add_column(sa.Column('codigo_acompanhamento', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('forma_pagamento', sa.Enum('pix', 'credito', 'debito', 'dinheiro', name='formapagamento'), nullable=True))
        batch_op.add_column(sa.Column('troco_para', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('pago', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('pago_em', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('bairro_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('bairro_nome', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('entregador_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('saiu_entrega_em', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('finalizado_em', sa.DateTime(), nullable=True))
        batch_op.alter_column(
            'status',
            existing_type=sa.Enum(*STATUS_ANTIGO, name='statuspedido'),
            type_=sa.Enum(*STATUS_NOVO, name='statuspedido'),
            existing_nullable=False,
        )
        batch_op.create_index('ix_pedidos_codigo_acompanhamento', ['codigo_acompanhamento'], unique=True)
        batch_op.create_foreign_key('fk_pedidos_entregador', 'entregadores', ['entregador_id'], ['id'])
        batch_op.create_foreign_key('fk_pedidos_bairro', 'bairros_entrega', ['bairro_id'], ['id'])

    # --- dados: preenche o que os registros existentes ainda não têm ---
    conexao = op.get_bind()
    for tabela, slugs in (("bebidas", SLUGS_BEBIDAS), ("ingredientes", SLUGS_INGREDIENTES)):
        for nome, slug in slugs.items():
            conexao.execute(sa.text(f"UPDATE {tabela} SET slug = :slug WHERE nome = :nome AND slug IS NULL"),
                            {"slug": slug, "nome": nome})
    # pedidos antigos ganham um código de acompanhamento e contam como já pagos
    for (pedido_id,) in conexao.execute(sa.text("SELECT id FROM pedidos WHERE codigo_acompanhamento IS NULL")).fetchall():
        conexao.execute(sa.text("UPDATE pedidos SET codigo_acompanhamento = :c, pago = 1 WHERE id = :id"),
                        {"c": secrets.token_urlsafe(16), "id": pedido_id})


def downgrade() -> None:
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.drop_constraint('fk_pedidos_bairro', type_='foreignkey')
        batch_op.drop_constraint('fk_pedidos_entregador', type_='foreignkey')
        batch_op.drop_index('ix_pedidos_codigo_acompanhamento')
        batch_op.alter_column(
            'status',
            existing_type=sa.Enum(*STATUS_NOVO, name='statuspedido'),
            type_=sa.Enum(*STATUS_ANTIGO, name='statuspedido'),
            existing_nullable=False,
        )
        for coluna in ('finalizado_em', 'saiu_entrega_em', 'entregador_id', 'bairro_nome', 'bairro_id',
                       'pago_em', 'pago', 'troco_para', 'forma_pagamento', 'codigo_acompanhamento'):
            batch_op.drop_column(coluna)

    with op.batch_alter_table('ingredientes') as batch_op:
        batch_op.drop_constraint('uq_ingredientes_slug', type_='unique')
        batch_op.drop_column('slug')

    with op.batch_alter_table('bebidas') as batch_op:
        batch_op.drop_constraint('uq_bebidas_slug', type_='unique')
        batch_op.drop_column('slug')

    op.drop_table('tamanhos_pizza')
    op.drop_table('horarios_funcionamento')
    op.drop_index('ix_entregadores_id', table_name='entregadores')
    op.drop_table('entregadores')
    op.drop_table('configuracoes')
    op.drop_index('ix_bairros_entrega_id', table_name='bairros_entrega')
    op.drop_table('bairros_entrega')
