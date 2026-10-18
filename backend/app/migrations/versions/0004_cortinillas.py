"""cortinillas: posición de la de inicio, plantilla única y fuera outro_enabled

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 12:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clips') as batch:
        batch.drop_column('outro_enabled')  # la cortinilla final es siempre: sin interruptor
        batch.add_column(sa.Column('cortinilla_at', sa.Float(), nullable=True))  # segundo del clip; None = la que elija el programador
    with op.batch_alter_table('brand_templates') as batch:
        batch.drop_column('intro')
        batch.drop_column('outro')
        batch.add_column(sa.Column('cortinilla', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('cortinilla_default', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    op.execute("UPDATE brand_templates SET cortinilla = '{}'")


def downgrade() -> None:
    with op.batch_alter_table('brand_templates') as batch:
        batch.drop_column('cortinilla_default')
        batch.drop_column('cortinilla')
        batch.add_column(sa.Column('outro', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('intro', sa.JSON(), nullable=True))
    op.execute("UPDATE brand_templates SET intro = '{}', outro = '{}'")
    with op.batch_alter_table('clips') as batch:
        batch.drop_column('cortinilla_at')
        batch.add_column(sa.Column('outro_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False))
