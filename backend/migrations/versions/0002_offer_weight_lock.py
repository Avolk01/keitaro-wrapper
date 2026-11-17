"""Persist locked offer shares.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "offer_weight_lock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.UniqueConstraint("stream_id", "offer_id", name="uq_offer_weight_lock_stream_offer"),
    )
    op.create_index("ix_offer_weight_lock_campaign_id", "offer_weight_lock", ["campaign_id"])


def downgrade():
    op.drop_index("ix_offer_weight_lock_campaign_id", "offer_weight_lock")
    op.drop_table("offer_weight_lock")
