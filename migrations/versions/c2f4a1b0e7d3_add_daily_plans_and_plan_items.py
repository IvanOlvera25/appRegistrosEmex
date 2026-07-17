"""add daily_plans and plan_items

Revision ID: c2f4a1b0e7d3
Revises: b1d8f0c9a4e2
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "c2f4a1b0e7d3"
down_revision = "b1d8f0c9a4e2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if "daily_plans" not in existing:
        op.create_table(
            "daily_plans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("plan_date", sa.Date(), nullable=False),
            sa.Column("plan_type", sa.String(length=20), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=True),
            sa.Column("worker_name", sa.String(length=120), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("validated_at", sa.DateTime(), nullable=True),
            sa.Column("validated_by_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["worker_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["validated_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("daily_plans", schema=None) as batch_op:
            batch_op.create_index("ix_daily_plans_plan_date", ["plan_date"], unique=False)

    if "plan_items" not in existing:
        op.create_table(
            "plan_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("unit_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("route_id", sa.Integer(), nullable=True),
            sa.Column("trip_type", sa.String(length=80), nullable=True),
            sa.Column("quantity", sa.String(length=60), nullable=True),
            sa.Column("is_extra", sa.Boolean(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("justification", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["plan_id"], ["daily_plans.id"]),
            sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if "plan_items" in existing:
        op.drop_table("plan_items")
    if "daily_plans" in existing:
        with op.batch_alter_table("daily_plans", schema=None) as batch_op:
            batch_op.drop_index("ix_daily_plans_plan_date")
        op.drop_table("daily_plans")
