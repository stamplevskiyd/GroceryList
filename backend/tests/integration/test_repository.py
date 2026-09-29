"""Базовый репозиторий: стандартные методы на примере пользователей (ADR-0005)."""

from typing import ClassVar
from uuid import uuid7

import pytest
from pydantic import BaseModel, computed_field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.schemas.users import UserCreate, UserUpdate


def _user(name: str) -> UserCreate:
    return UserCreate(username=name, password_hash=f"hash-{name}")


async def test_add_returns_persisted_object_with_uuid7_and_timestamps() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))

        assert user.id.version == 7
        assert user.created_at.tzinfo is not None
        assert user.updated_at.tzinfo is not None

    async with unit_of_work():
        stored = await user_repo.get(user.id)
        assert stored is not None
        assert stored.username == "anna"


async def test_add_accepts_extra_fields() -> None:
    class UsernameOnly(BaseModel):
        username: str

    class UsernameOnlyRepository(Repository[User, UsernameOnly, UserUpdate]):
        pass

    async with unit_of_work():
        user = await UsernameOnlyRepository(User).add(
            UsernameOnly(username="anna"), password_hash="from-service"
        )

    assert user.password_hash == "from-service"


async def test_add_writes_computed_fields_and_skips_excluded() -> None:
    class LoginCreate(BaseModel):
        login: str
        password_hash: str

        # mypy не поддерживает декораторы поверх @property; так рекомендует pydantic.
        @computed_field  # type: ignore[prop-decorator]
        @property
        def username(self) -> str:
            return self.login.strip().lower()

    class LoginRepository(Repository[User, LoginCreate, UserUpdate]):
        exclude_on_write: ClassVar[frozenset[str]] = frozenset({"login"})

    async with unit_of_work():
        user = await LoginRepository(User).add(LoginCreate(login="  Anna ", password_hash="h"))

    assert user.username == "anna"


async def test_add_all() -> None:
    async with unit_of_work():
        users = await user_repo.add_all([_user("anna"), _user("boris")])

    assert [user.username for user in users] == ["anna", "boris"]
    assert all(user.id is not None for user in users)


async def test_get_missing_returns_none() -> None:
    async with unit_of_work():
        assert await user_repo.get(uuid7()) is None


async def test_get_by_ids_returns_only_existing() -> None:
    async with unit_of_work():
        anna, boris = await user_repo.add_all([_user("anna"), _user("boris")])
        found = await user_repo.get_by_ids([anna.id, uuid7()])

    assert {user.id for user in found} == {anna.id}
    assert boris.id not in {user.id for user in found}


async def test_get_by_ids_with_empty_list() -> None:
    async with unit_of_work():
        assert await user_repo.get_by_ids([]) == []


async def test_update_changes_only_passed_fields() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await user_repo.update(user, UserUpdate(password_hash="new-hash"))
        # updated_at доступен без неявного запроса (eager_defaults).
        assert user.updated_at is not None

    async with unit_of_work():
        stored = await user_repo.get(user.id)
        assert stored is not None
        assert (stored.username, stored.password_hash) == ("anna", "new-hash")


async def test_delete() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await user_repo.delete(user)

    async with unit_of_work():
        assert await user_repo.get(user.id) is None


async def test_delete_by_ids_returns_count() -> None:
    async with unit_of_work():
        anna, boris, _ = await user_repo.add_all([_user("anna"), _user("boris"), _user("vera")])
        deleted = await user_repo.delete_by_ids([anna.id, boris.id, uuid7()])

    assert deleted == 2


async def test_delete_by_ids_with_empty_list() -> None:
    async with unit_of_work():
        assert await user_repo.delete_by_ids([]) == 0


async def test_duplicate_username_raises_and_rolls_back() -> None:
    async with unit_of_work():
        await user_repo.add(_user("anna"))

    async def add_boris_and_duplicate_anna() -> None:
        async with unit_of_work():
            await user_repo.add(_user("boris"))
            await user_repo.add(_user("anna"))

    with pytest.raises(IntegrityError):
        await add_boris_and_duplicate_anna()

    # boris из упавшей единицы работы тоже не сохранился — откат целиком.
    async with unit_of_work() as session:
        names = set(await session.scalars(select(User.username)))
    assert names == {"anna"}


async def test_repository_outside_unit_of_work_raises() -> None:
    with pytest.raises(RuntimeError, match="unit_of_work"):
        await user_repo.add(_user("anna"))


class _UserRename(BaseModel):
    login: str | None = None

    # mypy не поддерживает декораторы поверх @property; так рекомендует pydantic.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def username(self) -> str | None:
        # None — «не менялось»: исходное поле не передано.
        return None if self.login is None else self.login.strip().lower()


class _RenameRepository(Repository[User, UserCreate, _UserRename]):
    exclude_on_write: ClassVar[frozenset[str]] = frozenset({"login"})


async def test_update_writes_computed_fields_derived_from_passed_values() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await _RenameRepository(User).update(user, _UserRename(login="  Boris "))

    assert user.username == "boris"


async def test_update_skips_computed_fields_that_are_none() -> None:
    async with unit_of_work():
        user = await user_repo.add(_user("anna"))
        await _RenameRepository(User).update(user, _UserRename())

    assert user.username == "anna"
