from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grocery.db.base import Base, Entity
from grocery.db.types import PydanticJSON
from grocery.domain.enums import MemberRole
from grocery.schemas.sources import ItemSource

item_tags = Table(
    "item_tags",
    Base.metadata,
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class ShoppingList(Entity):
    __tablename__ = "shopping_lists"
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class ShoppingListMember(Entity):
    __tablename__ = "shopping_list_members"
    __table_args__ = (UniqueConstraint("shopping_list_id", "user_id"),)
    shopping_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[MemberRole] = mapped_column(
        Enum(
            MemberRole,
            native_enum=False,
            length=32,
            values_callable=lambda cls: [v.value for v in cls],
        )
    )


class Tag(Entity):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("shopping_list_id", "name_normalized"),)
    shopping_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    name_normalized: Mapped[str] = mapped_column(String(255))


class Item(Entity):
    __tablename__ = "items"
    __table_args__ = (
        Index(
            "ix_items_open_lookup",
            "shopping_list_id",
            "name_normalized",
            "unit",
            postgresql_where=~Column("is_bought", Boolean),
        ),
    )
    shopping_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    name_normalized: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric())
    unit: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text())
    is_bought: Mapped[bool] = mapped_column(server_default=false(), default=False)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sources: Mapped[list[ItemSource]] = mapped_column(PydanticJSON(list[ItemSource]))
    tags: Mapped[list[Tag]] = relationship(secondary=item_tags, lazy="raise", order_by=Tag.name)
