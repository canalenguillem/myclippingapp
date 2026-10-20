"""tramos de pantalla compartida (tuits, webs) de cada clip, en segundos del vídeo original

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-20 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clips', sa.Column('screen_ranges', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clips') as batch:
        batch.drop_column('screen_ranges')
