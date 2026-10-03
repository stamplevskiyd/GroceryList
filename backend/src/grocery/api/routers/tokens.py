"""Cookie-protected personal access token management."""

from uuid import UUID

from fastapi import APIRouter, Response

from grocery.api.deps import AppSourceDep, Authenticated
from grocery.api.errors import PROTECTED_RESPONSES
from grocery.schemas.tokens import TokenCreate, TokenIssued, TokenRead
from grocery.services.auth import tokens as service

router = APIRouter(
    prefix="/tokens", tags=["tokens"], dependencies=[Authenticated], responses=PROTECTED_RESPONSES
)


@router.get("", response_model=list[TokenRead])
async def get(response: Response) -> list[TokenRead]:
    response.headers["Cache-Control"] = "no-store"
    return await service.list_tokens()


@router.post("", response_model=TokenIssued)
async def create(data: TokenCreate, source: AppSourceDep, response: Response) -> TokenIssued:
    response.headers["Cache-Control"] = "no-store"
    return await service.issue_token(data)


@router.delete("/{id}", status_code=204, response_class=Response, response_model=None)
async def revoke(id: UUID, source: AppSourceDep) -> Response:
    await service.revoke_token(id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
