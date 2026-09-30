from decimal import Decimal

from grocery.db.models import Item, ShoppingList, Tag
from grocery.db.repositories.shopping import item_repo, shopping_list_repo, tag_repo
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.schemas.items import ItemCreate
from grocery.schemas.shopping_lists import ShoppingListCreate
from grocery.schemas.sources import AppAttribution
from grocery.schemas.tags import TagCreate
from grocery.schemas.users import UserCreate


async def test_storage_roundtrip_and_eager_tags() -> None:
    async with unit_of_work():
        user = await user_repo.add(UserCreate(username="owner", password_hash="hash"))
        shopping_list = await shopping_list_repo.add(
            ShoppingListCreate(name="Покупки", owner_id=user.id)
        )
        tag = await tag_repo.add(TagCreate(name="Для супа", shopping_list_id=shopping_list.id))
        item = await item_repo.add(
            ItemCreate(name="Лук", quantity=Decimal("1.5"), unit="кг"),
            shopping_list_id=shopping_list.id,
            sources=[AppAttribution()],
            tags=[tag],
        )
    async with unit_of_work():
        stored = await item_repo.get(item.id)
        assert isinstance(stored, Item)
        assert stored.quantity == Decimal("1500")
        assert stored.sources == [AppAttribution()]
        assert [tag.name for tag in stored.tags] == ["Для супа"]
        assert stored.id.version == 7
        assert isinstance(await shopping_list_repo.get(shopping_list.id), ShoppingList)
        assert isinstance(await tag_repo.get(tag.id), Tag)
        assert await item_repo.find_open_by_name(shopping_list.id, "лук", "г") is stored
        assert await item_repo.find_open_by_name(shopping_list.id, "лук", "шт") is None
        stored.is_bought = True
    async with unit_of_work():
        assert await item_repo.find_open_by_name(shopping_list.id, "лук", "г") is None
