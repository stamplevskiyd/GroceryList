from uuid import uuid7

import pytest
from sqlalchemy import select

from grocery.db.models import PersonalAccessToken, User
from grocery.db.repositories.users import user_repo
from grocery.db.session import unit_of_work
from grocery.domain.errors import NotFoundError
from grocery.schemas.tokens import TokenCreate
from grocery.services.auth import acting_as, create_user
from grocery.services.auth.sessions import token_hash
from grocery.services.auth.tokens import issue_token, list_tokens, revoke_token, verify_bearer


async def test_issue_list_verify_and_revoke(owner: User) -> None:
    async with unit_of_work() as db:
        with acting_as(owner):
            issued = await issue_token(TokenCreate(name="  Claude Code  "))
            raw = issued.token.get_secret_value()
            assert raw.startswith("gl_pat_")
            assert raw not in repr(issued)
            assert issued.model_dump(mode="json")["token"] == raw
            stored = await db.scalar(select(PersonalAccessToken))
            assert stored is not None
            assert stored.token_hash == token_hash(raw)
            assert raw not in repr(stored)
            listed = await list_tokens()
            assert listed[0].name == "Claude Code"
            assert "token" not in listed[0].model_dump()
    async with unit_of_work():
        identity = await verify_bearer(raw)
        assert identity is not None
        assert identity.user_id == owner.id
        assert identity.client_id == str(issued.id)
        assert identity.client_name == "Claude Code"
        assert identity.resource.endswith("/mcp")
    async with unit_of_work():
        with acting_as(owner):
            assert (await list_tokens())[0].last_used_at is not None
            await revoke_token(issued.id)
            await revoke_token(issued.id)
            assert (await list_tokens())[0].revoked_at is not None
            assert await verify_bearer(raw) is None


@pytest.mark.parametrize("raw", ["", "unknown", "gl_pat_unknown", "gl_at_unknown"])
async def test_invalid_bearer(raw: str) -> None:
    async with unit_of_work():
        assert await verify_bearer(raw) is None


async def test_owner_isolation_and_deleted_user(owner: User) -> None:
    async with unit_of_work():
        with acting_as(owner):
            issued = await issue_token(TokenCreate(name="Code"))
        other = await create_user("boris", "password")
        with acting_as(other):
            assert await list_tokens() == []
            with pytest.raises(NotFoundError):
                await revoke_token(issued.id)
            with pytest.raises(NotFoundError):
                await revoke_token(uuid7())
        stored_user = await user_repo.get(owner.id)
        assert stored_user is not None
        await user_repo.delete(stored_user)
    async with unit_of_work():
        assert await verify_bearer(issued.token.get_secret_value()) is None


async def test_issue_rolls_back(owner: User) -> None:
    with pytest.raises(RuntimeError, match="rollback"):  # noqa: PT012 — UoW rollback
        async with unit_of_work():
            with acting_as(owner):
                issued = await issue_token(TokenCreate(name="Code"))
                raise RuntimeError("rollback")
    async with unit_of_work():
        assert await verify_bearer(issued.token.get_secret_value()) is None
