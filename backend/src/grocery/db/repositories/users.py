"""Репозиторий пользователей."""

from sqlalchemy import select

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.db.session import get_current_session
from grocery.schemas.users import UserCreate, UserUpdate


class UserRepository(Repository[User, UserCreate, UserUpdate]):
    async def by_username(self, username: str) -> User | None:
        return await get_current_session().scalar(select(User).where(User.username == username))


user_repo = UserRepository(User)
