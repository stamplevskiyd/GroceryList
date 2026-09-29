"""Репозиторий пользователей."""

from grocery.db.models import User
from grocery.db.repositories.base import Repository
from grocery.schemas.users import UserCreate, UserUpdate


class UserRepository(Repository[User, UserCreate, UserUpdate]):
    pass


user_repo = UserRepository(User)
