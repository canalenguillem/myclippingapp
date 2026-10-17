"""estado enum, speakers, silencios y partes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 19:41:17.227208
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clips', sa.Column('parts', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('projects', sa.Column('silences_path', sa.String(length=1024), nullable=True))
    op.add_column('projects', sa.Column('speakers', sa.JSON(), server_default='{}', nullable=False))
    # `status` sigue siendo VARCHAR(16); ahora lo valida el Enum de Python (ProjectStatus).
    # El estado provisional `transcribed` desaparece: esos proyectos quedan a la espera de detectar clips.
    op.execute("UPDATE projects SET status = 'detecting' WHERE status = 'transcribed'")


def downgrade() -> None:
    op.execute("UPDATE projects SET status = 'transcribed' WHERE status = 'detecting'")
    op.drop_column('projects', 'speakers')
    op.drop_column('projects', 'silences_path')
    op.drop_column('clips', 'parts')
