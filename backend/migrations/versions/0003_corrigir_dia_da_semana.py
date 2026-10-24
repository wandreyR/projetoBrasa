"""corrige horarios_funcionamento.dia_semana criado como AUTO_INCREMENT no MySQL

Na primeira versão da 0002 a chave dia_semana virou AUTO_INCREMENT no MySQL: o dia 0
(segunda-feira) era trocado por um número automático e o seed gravava dias errados.
Esta migração tira o AUTO_INCREMENT e, se os dias gravados estiverem fora de 0..6,
recria a semana com o horário padrão (aberto o dia todo).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conexao = op.get_bind()
    if conexao.dialect.name == "mysql":
        op.execute("ALTER TABLE horarios_funcionamento MODIFY dia_semana INT NOT NULL")

    dias = {d for (d,) in conexao.execute(sa.text("SELECT dia_semana FROM horarios_funcionamento"))}
    if dias and dias != set(range(7)):
        conexao.execute(sa.text("DELETE FROM horarios_funcionamento"))
        for d in range(7):
            conexao.execute(
                sa.text("INSERT INTO horarios_funcionamento (dia_semana, abre, fecha, fechado) "
                        "VALUES (:d, '00:00:00', '23:59:00', 0)"),
                {"d": d},
            )


def downgrade() -> None:
    pass  # não há o que desfazer: o AUTO_INCREMENT era um defeito
