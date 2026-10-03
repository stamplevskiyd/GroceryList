"""Keep only event-specific payload fields in existing snapshots.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE events SET payload = CASE
            WHEN type = 'items_added' THEN jsonb_build_object('results', payload->'results')
            WHEN type IN ('tag_renamed', 'tags_merged') THEN
                jsonb_build_object('tag', payload->'tag', 'previous_tag', payload->'previous_tag')
            WHEN type = 'tag_deleted' THEN jsonb_build_object('tag', payload->'tag')
            ELSE jsonb_build_object('items', payload->'items')
        END
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE events SET payload =
            '{"items": [], "results": [], "tag": null, "previous_tag": null}'::jsonb || payload
    """)
