"""Current user and accessible shopping lists."""

from fastapi import APIRouter

from grocery.api.deps import Authenticated
from grocery.api.errors import PROTECTED_RESPONSES
from grocery.schemas.auth import MeRead
from grocery.services import auth

router = APIRouter(tags=["me"], dependencies=[Authenticated], responses=PROTECTED_RESPONSES)


@router.get("/me")
async def me() -> MeRead:
    return await auth.get_me()
