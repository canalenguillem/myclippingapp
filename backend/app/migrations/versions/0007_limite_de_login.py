"""intentos de login fallidos (límite por email e IP)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'login_failures',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_login_failures_email', 'login_failures', ['email'])
    op.create_index('ix_login_failures_ip', 'login_failures', ['ip'])
    op.create_index('ix_login_failures_created_at', 'login_failures', ['created_at'])


def downgrade() -> None:
    op.drop_table('login_failures')
