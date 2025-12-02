"""Add deposits and insurance tables

Revision ID: 96e44fff2db2
Revises: 95d33eff1da1
Create Date: 2025-12-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96e44fff2db2'
down_revision: Union[str, Sequence[str], None] = '95d33eff1da1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Создаем таблицу ВКЛАДОВ ---
    op.create_table('deposits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('term_months', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deposits_id'), 'deposits', ['id'], unique=False)

    # --- Создаем таблицу СТРАХОВАНИЯ ---
    op.create_table('insurances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('insurance_type', sa.String(), nullable=False),
        sa.Column('coverage_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('monthly_cost', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('term_months', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_insurances_id'), 'insurances', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_insurances_id'), table_name='insurances')
    op.drop_table('insurances')
    op.drop_index(op.f('ix_deposits_id'), table_name='deposits')
    op.drop_table('deposits')