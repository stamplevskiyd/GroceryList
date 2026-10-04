"""Репозиторий пользователей."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.users import UserCreate, UserUpdate


class UserRepository(Repository[User, UserCreate, UserUpdate]):
    async def create_if_available(self, data: UserCreate) -> User | None:
        # Concurrent registrations for the same name must produce one account.
        return await get_current_session().scalar(
            insert(User)
            .values(**data.model_dump())
            .on_conflict_do_nothing(index_elements=[User.username])
            .returning(User)
        )

    async def by_username(self, username: str) -> User | None:
        return await get_current_session().scalar(select(User).where(User.username == username))


user_repo = UserRepository(User)
