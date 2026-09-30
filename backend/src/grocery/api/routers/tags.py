"""Tag REST endpoints: validation and delegation to the shopping service."""

from uuid import UUID

from fastapi import APIRouter, Response

from grocery.api.deps import AppSourceDep, Authenticated
from grocery.api.errors import PROTECTED_RESPONSES
from grocery.schemas.common import CountRead
from grocery.schemas.items import TagRead
from grocery.schemas.tags import TagBulk, TagUpdate, TagUsageRead
from grocery.services import shopping_list_service as service

router = APIRouter(
    prefix="/tags", tags=["tags"], dependencies=[Authenticated], responses=PROTECTED_RESPONSES
)


@router.get("", response_model=list[TagUsageRead])
async def get(shopping_list_id: UUID) -> list[TagUsageRead]:
    return await service.list_tags(shopping_list_id)


@router.patch("/{id}", response_model=TagRead)
async def rename(id: UUID, data: TagUpdate, source: AppSourceDep) -> TagRead:
    return await service.rename_tag(id, data.name, source)


@router.delete("/{id}", status_code=204, response_class=Response, response_model=None)
async def delete(id: UUID, source: AppSourceDep) -> Response:
    await service.delete_tag(id, source)
    return Response(status_code=204)


@router.post("/{id}/bulk", response_model=CountRead)
async def bulk(id: UUID, data: TagBulk, source: AppSourceDep) -> CountRead:
    return CountRead(count=await service.bulk_tag(id, data.action, source))
