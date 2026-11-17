"""Remember offers seen in campaign streams.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stream_offer_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer_snapshot_stream_offer"),
    )
    op.create_index("ix_stream_offer_snapshot_campaign_id", "stream_offer_snapshot", ["campaign_id"])


def downgrade():
    op.drop_index("ix_stream_offer_snapshot_campaign_id", "stream_offer_snapshot")
    op.drop_table("stream_offer_snapshot")
