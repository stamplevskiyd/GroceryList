from argon2 import PasswordHasher
from sqlalchemy import func, select

from grocery.__main__ import create_user_command
from grocery.db.models import ShoppingList, ShoppingListMember, User
from grocery.db.session import unit_of_work


async def test_create_user_command_and_duplicate_does_not_create_second_list() -> None:
    assert await create_user_command("anna", "secret-password") == 0
    assert await create_user_command("anna", "different-password") == 1
    async with unit_of_work() as session:
        user = await session.scalar(select(User))
        assert user is not None
        assert PasswordHasher().verify(user.password_hash, "secret-password")
        assert await session.scalar(select(func.count()).select_from(ShoppingList)) == 1
        assert await session.scalar(select(func.count()).select_from(ShoppingListMember)) == 1


async def test_invalid_user_command_does_not_write() -> None:
    assert await create_user_command(" ", "password") == 1
    assert await create_user_command("anna", "") == 1
    async with unit_of_work() as session:
        assert await session.scalar(select(User.id)) is None
