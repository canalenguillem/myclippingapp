"""error de la última subida a YouTube

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clips', sa.Column('upload_error', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clips') as batch:
        batch.drop_column('upload_error')
