"""publicar en YouTube al terminar el render (privacidad elegida, o NULL si no)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clips', sa.Column('auto_publish', sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clips') as batch:
        batch.drop_column('auto_publish')
