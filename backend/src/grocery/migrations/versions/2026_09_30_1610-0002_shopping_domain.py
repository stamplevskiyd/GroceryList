"""shopping domain

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30 16:10:53.574895+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_shopping_lists_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_lists")),
    )
    op.create_index(
        op.f("ix_shopping_lists_owner_id"), "shopping_lists", ["owner_id"], unique=False
    )
    op.create_table(
        "events",
        sa.Column("shopping_list_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "items_added",
                "item_updated",
                "items_bought",
                "items_unbought",
                "items_deleted",
                "bought_cleared",
                "tag_renamed",
                "tags_merged",
                "tag_deleted",
                name="eventtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shopping_list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_events_shopping_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_events_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index(
        op.f("ix_events_shopping_list_id"), "events", ["shopping_list_id"], unique=False
    )
    op.create_table(
        "items",
        sa.Column("shopping_list_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_normalized", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_bought", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("bought_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shopping_list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_items_shopping_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
    )
    op.create_index(
        "ix_items_open_lookup",
        "items",
        ["shopping_list_id", "name_normalized", "unit"],
        unique=False,
        postgresql_where=sa.text("NOT is_bought"),
    )
    op.create_index(op.f("ix_items_shopping_list_id"), "items", ["shopping_list_id"], unique=False)
    op.create_table(
        "shopping_list_members",
        sa.Column("shopping_list_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "editor", name="memberrole", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shopping_list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_shopping_list_members_shopping_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_shopping_list_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_list_members")),
        sa.UniqueConstraint(
            "shopping_list_id",
            "user_id",
            name=op.f("uq_shopping_list_members_shopping_list_id_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_shopping_list_members_user_id"), "shopping_list_members", ["user_id"], unique=False
    )
    op.create_table(
        "tags",
        sa.Column("shopping_list_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_normalized", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shopping_list_id"],
            ["shopping_lists.id"],
            name=op.f("fk_tags_shopping_list_id_shopping_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint(
            "shopping_list_id",
            "name_normalized",
            name=op.f("uq_tags_shopping_list_id_name_normalized"),
        ),
    )
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_item_tags_item_id_items"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_item_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("item_id", "tag_id", name=op.f("pk_item_tags")),
    )


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_table("tags")
    op.drop_index(op.f("ix_shopping_list_members_user_id"), table_name="shopping_list_members")
    op.drop_table("shopping_list_members")
    op.drop_index(op.f("ix_items_shopping_list_id"), table_name="items")
    op.drop_index(
        "ix_items_open_lookup", table_name="items", postgresql_where=sa.text("NOT is_bought")
    )
    op.drop_table("items")
    op.drop_index(op.f("ix_events_shopping_list_id"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_shopping_lists_owner_id"), table_name="shopping_lists")
    op.drop_table("shopping_lists")
