import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from grocery.db.models import Session, User
from grocery.db.repositories.shopping import member_repo, shopping_list_repo
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.domain.enums import MemberRole
from grocery.schemas.shopping_lists import MemberCreate
from grocery.services.auth import AuthError, acting_as, create_user, get_me
from grocery.services.auth.sessions import issue_session, logout, resolve_session, token_hash


@pytest.fixture
async def owner() -> User:
    async with unit_of_work():
        return await create_user("anna", "password")


async def test_session_stores_only_hash_and_resolves_user(owner: User) -> None:
    async with unit_of_work() as db:
        before = datetime.now(UTC)
        issued = await issue_session(owner.id, "phone")
        stored = await db.scalar(select(Session))
        assert stored is not None
        assert issued.token.startswith("gl_sess_")
        assert stored.token_hash == hashlib.sha256(issued.token.encode()).hexdigest()
        assert token_hash(issued.token) == stored.token_hash
        assert stored.token_hash != issued.token
        assert stored.device_id == "phone"
        assert stored.user_id == owner.id
        assert stored.expires_at == issued.expires_at
        assert stored.expires_at.tzinfo is not None
        assert stored.expires_at > before
        assert issued.token not in repr(stored)
        assert issued.token not in repr(issued)
    async with unit_of_work():
        user = await resolve_session(issued.token)
        assert (user.id, user.username) == (owner.id, owner.username)


@pytest.mark.parametrize("token", ["", "gl_sess_unknown"])
async def test_unknown_token_is_rejected(token: str) -> None:
    with pytest.raises(AuthError):
        async with unit_of_work():
            await resolve_session(token)


async def test_expired_session_is_rejected_without_deleting_it(owner: User) -> None:
    async with unit_of_work():
        issued = await issue_session(owner.id, "phone")
    async with unit_of_work() as db:
        stored = await db.scalar(select(Session))
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(AuthError):
        async with unit_of_work():
            await resolve_session(issued.token)
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 1


async def test_configured_ttl_is_fixed_and_not_extended(
    owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "60")
    async with unit_of_work():
        before = datetime.now(UTC)
        issued = await issue_session(owner.id, "phone")
        after = datetime.now(UTC)
        assert before + timedelta(seconds=60) <= issued.expires_at <= after + timedelta(seconds=60)
    async with unit_of_work() as db:
        await resolve_session(issued.token)
        stored = await db.scalar(select(Session))
        assert stored is not None
        assert stored.expires_at == issued.expires_at


async def test_logout_only_revokes_selected_device_and_is_idempotent(owner: User) -> None:
    async with unit_of_work():
        phone = await issue_session(owner.id, "phone")
        tablet = await issue_session(owner.id, "tablet")
        assert phone.token != tablet.token
    async with unit_of_work() as db:
        await logout(phone.token)
        await logout(phone.token)
        await logout("unknown")
        assert await db.scalar(select(func.count()).select_from(Session)) == 1
    with pytest.raises(AuthError):
        async with unit_of_work():
            await resolve_session(phone.token)
    async with unit_of_work():
        assert (await resolve_session(tablet.token)).id == owner.id


async def test_session_creation_rolls_back_with_unit_of_work(owner: User) -> None:
    with pytest.raises(RuntimeError, match="rollback"):  # noqa: PT012 — проверка отката UoW
        async with unit_of_work():
            issued = await issue_session(owner.id, "phone")
            raise RuntimeError("rollback")
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 0
    with pytest.raises(AuthError):
        async with unit_of_work():
            await resolve_session(issued.token)


async def test_user_deletion_cascades_sessions(owner: User) -> None:
    async with unit_of_work():
        issued = await issue_session(owner.id, "phone")
        user = await user_repo.get(owner.id)
        assert user is not None
        await user_repo.delete(user)
    async with unit_of_work() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 0
    with pytest.raises(AuthError):
        async with unit_of_work():
            await resolve_session(issued.token)


async def test_me_contains_only_public_identity_and_membership_lists(owner: User) -> None:
    async with unit_of_work():
        other = await create_user("boris", "password")
        shared_list = (await shopping_list_repo.for_user(other.id))[0]
        await member_repo.add(
            MemberCreate(shopping_list_id=shared_list.id, user_id=owner.id, role=MemberRole.EDITOR)
        )
        await create_user("private", "password")
    async with unit_of_work():
        user = await user_repo.get(owner.id)
        assert user is not None
        with acting_as(user):
            me = await get_me()
        assert me.id == owner.id
        assert me.username == owner.username
        assert set(me.model_dump()) == {"id", "username", "shopping_lists"}
        assert len(me.shopping_lists) == 2
        assert shared_list.id in {shopping_list.id for shopping_list in me.shopping_lists}
        assert all(set(item.model_dump()) == {"id", "name"} for item in me.shopping_lists)
        assert owner.password_hash not in me.model_dump_json()


async def test_me_requires_authenticated_context() -> None:
    with pytest.raises(AuthError):
        async with unit_of_work():
            await get_me()
