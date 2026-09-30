from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from grocery.db.models import Event, Item, ShoppingList, ShoppingListMember, Tag
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.events import EventCreate
from grocery.schemas.items import ItemCreate, ItemUpdate
from grocery.schemas.shopping_lists import MemberCreate, ShoppingListCreate, ShoppingListUpdate
from grocery.schemas.tags import TagCreate, TagUpdate


class ShoppingListRepository(Repository[ShoppingList, ShoppingListCreate, ShoppingListUpdate]):
    async def lock(self, id: UUID) -> ShoppingList | None:
        return await get_current_session().scalar(
            select(ShoppingList).where(ShoppingList.id == id).with_for_update()
        )

    async def has_member(self, id: UUID, user_id: UUID) -> bool:
        return (
            await get_current_session().scalar(
                select(ShoppingListMember.id).where(
                    ShoppingListMember.shopping_list_id == id, ShoppingListMember.user_id == user_id
                )
            )
            is not None
        )

    async def for_user(self, user_id: UUID) -> list[ShoppingList]:
        return list(
            await get_current_session().scalars(
                select(ShoppingList)
                .join(ShoppingListMember, ShoppingListMember.shopping_list_id == ShoppingList.id)
                .where(ShoppingListMember.user_id == user_id)
                .order_by(ShoppingList.created_at)
            )
        )


class ItemRepository(Repository[Item, ItemCreate, ItemUpdate]):
    exclude_on_write: ClassVar[frozenset[str]] = frozenset({"tags"})

    async def get(self, id: UUID) -> Item | None:
        return await get_current_session().scalar(
            select(Item)
            .where(Item.id == id)
            .options(selectinload(Item.tags))
            .execution_options(populate_existing=True)
        )

    async def get_by_ids(self, ids: Sequence[UUID]) -> list[Item]:
        return list(
            await get_current_session().scalars(
                select(Item)
                .where(Item.id.in_(ids))
                .options(selectinload(Item.tags))
                .execution_options(populate_existing=True)
            )
        )

    async def for_shopping_list(self, id: UUID, *, include_bought: bool = False) -> list[Item]:
        statement = select(Item).where(Item.shopping_list_id == id).options(selectinload(Item.tags))
        if not include_bought:
            statement = statement.where(Item.is_bought.is_(False))
        statement = statement.order_by(
            Item.is_bought,
            Item.bought_at.desc().nulls_last(),
            Item.created_at.desc(),
            Item.id.desc(),
        )
        return list(await get_current_session().scalars(statement))

    async def find_open_by_name(
        self, shopping_list_id: UUID, name_normalized: str, unit: str | None
    ) -> Item | None:
        return await get_current_session().scalar(
            select(Item)
            .where(
                Item.shopping_list_id == shopping_list_id,
                Item.name_normalized == name_normalized,
                Item.unit == unit,
                Item.is_bought.is_(False),
            )
            .options(selectinload(Item.tags))
            .order_by(Item.created_at, Item.id)
            .limit(1)
        )


@dataclass(frozen=True, slots=True)
class TagUsage:
    tag: Tag
    open_count: int


class TagRepository(Repository[Tag, TagCreate, TagUpdate]):
    async def by_name(self, shopping_list_id: UUID, name_normalized: str) -> Tag | None:
        return await get_current_session().scalar(
            select(Tag).where(
                Tag.shopping_list_id == shopping_list_id, Tag.name_normalized == name_normalized
            )
        )

    async def usage(self, shopping_list_id: UUID) -> list[TagUsage]:
        # OUTER JOIN сохраняет теги без позиций; bought не входит в open_count.
        from grocery.db.models.shopping import item_tags

        statement = (
            select(Tag, func.count(Item.id))
            .outerjoin(item_tags, item_tags.c.tag_id == Tag.id)
            .outerjoin(Item, (Item.id == item_tags.c.item_id) & Item.is_bought.is_(False))
            .where(Tag.shopping_list_id == shopping_list_id)
            .group_by(Tag.id)
            .order_by(Tag.name_normalized)
        )
        rows = await get_current_session().execute(statement)
        return [TagUsage(tag=row[0], open_count=row[1]) for row in rows]


shopping_list_repo = ShoppingListRepository(ShoppingList)
member_repo = Repository[ShoppingListMember, MemberCreate, BaseModel](ShoppingListMember)
item_repo = ItemRepository(Item)
tag_repo = TagRepository(Tag)
event_repo = Repository[Event, EventCreate, BaseModel](Event)
