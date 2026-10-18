"""librería de assets del usuario

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 20:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'assets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='object'),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('path', sa.String(length=1024), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('license_note', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('width', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('height', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_assets_user_id', 'assets', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_assets_user_id', table_name='assets')
    op.drop_table('assets')
