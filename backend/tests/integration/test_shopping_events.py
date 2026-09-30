from uuid import uuid7

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from grocery.db.models import Event, ShoppingList, ShoppingListMember
from grocery.db.session import unit_of_work
from grocery.domain.enums import EventType, MemberRole
from grocery.schemas.events import EventPayload
from grocery.schemas.sources import AppSource
from grocery.services.auth import AuthError, acting_as, create_user, get_current_user
from grocery.services.event_hub import event_hub
from grocery.services.events import record_event


async def test_create_user_and_context_reset() -> None:
    async with unit_of_work() as session:
        user = await create_user("anna", "secret-password")
        assert PasswordHasher().verify(user.password_hash, "secret-password")
        shopping_list = await session.scalar(
            select(ShoppingList).where(ShoppingList.owner_id == user.id)
        )
        assert shopping_list is not None
        membership = await session.scalar(
            select(ShoppingListMember).where(ShoppingListMember.user_id == user.id)
        )
        assert membership is not None
        assert membership.shopping_list_id == shopping_list.id
        assert membership.role == MemberRole.OWNER
        with acting_as(user):
            assert get_current_user() is user
        with pytest.raises(AuthError):
            get_current_user()


@pytest.mark.real_commits
async def test_event_published_after_commit_only() -> None:
    async with unit_of_work() as session:
        user = await create_user("anna", "secret-password")
        shopping_list = await session.scalar(select(ShoppingList))
        assert shopping_list is not None
    with event_hub.subscribe(shopping_list.id) as queue, event_hub.subscribe(uuid7()) as other:
        with acting_as(user):
            async with unit_of_work():
                stored = await record_event(
                    shopping_list.id,
                    EventType.ITEMS_ADDED,
                    AppSource(device_id="phone"),
                    EventPayload(),
                )
                assert queue.empty()
        published = queue.get_nowait()
        assert published.id == stored.id
        assert published.source == AppSource(device_id="phone")
        assert other.empty()
        async with unit_of_work() as session:
            persisted = await session.get(Event, stored.id)
            assert persisted is not None
            assert persisted.payload == EventPayload()


@pytest.mark.real_commits
async def test_rollback_never_publishes() -> None:
    async with unit_of_work() as session:
        user = await create_user("anna", "secret-password")
        shopping_list = await session.scalar(select(ShoppingList))
        assert shopping_list is not None
    with event_hub.subscribe(shopping_list.id) as queue:
        with pytest.raises(ValueError, match="abort"), acting_as(user):  # noqa: PT012 — проверяем откат всей транзакции
            async with unit_of_work():
                await record_event(
                    shopping_list.id,
                    EventType.ITEMS_ADDED,
                    AppSource(device_id="phone"),
                    EventPayload(),
                )
                raise ValueError("abort")
        assert queue.empty()
    async with unit_of_work() as session:
        assert await session.scalar(select(Event.id)) is None
