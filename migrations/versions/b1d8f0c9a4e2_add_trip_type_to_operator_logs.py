"""add trip type to operator logs

Revision ID: b1d8f0c9a4e2
Revises: f7f7f92272b3
Create Date: 2026-05-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1d8f0c9a4e2"
down_revision = "f7f7f92272b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("operator_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trip_type", sa.String(length=80), nullable=True))


def downgrade():
    with op.batch_alter_table("operator_logs", schema=None) as batch_op:
        batch_op.drop_column("trip_type")
