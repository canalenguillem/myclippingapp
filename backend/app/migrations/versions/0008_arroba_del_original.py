"""@ del canal del vídeo original (para etiquetarlo en la descripción)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('source_handle', sa.String(80), nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('source_handle')
