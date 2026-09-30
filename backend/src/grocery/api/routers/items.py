"""Item REST endpoints: validation and delegation to the shopping service."""

from uuid import UUID

from fastapi import APIRouter, Response

from grocery.api.deps import AppSourceDep, Authenticated
from grocery.api.errors import PROTECTED_RESPONSES
from grocery.schemas.common import CountRead
from grocery.schemas.items import (
    AddItemResult,
    AddItems,
    ClearBought,
    ItemRead,
    ItemUpdate,
    QuickAdd,
    QuickAddResult,
    SetBought,
)
from grocery.services import shopping_list_service as service

router = APIRouter(
    prefix="/items", tags=["items"], dependencies=[Authenticated], responses=PROTECTED_RESPONSES
)


@router.get("", response_model=list[ItemRead])
async def get(shopping_list_id: UUID, include_bought: bool = False) -> list[ItemRead]:
    return await service.get_items(shopping_list_id, include_bought=include_bought)


@router.post("", response_model=list[AddItemResult])
async def add(data: AddItems, source: AppSourceDep) -> list[AddItemResult]:
    return await service.add_items(data, source)


@router.post("/quick-add", response_model=QuickAddResult)
async def quick_add(data: QuickAdd, source: AppSourceDep) -> QuickAddResult:
    return await service.quick_add(data, source)


@router.post("/bought", response_model=list[ItemRead])
async def bought(data: SetBought, source: AppSourceDep) -> list[ItemRead]:
    return await service.set_bought(data.shopping_list_id, data.ids, data.bought, source)


@router.post("/clear-bought", response_model=CountRead)
async def clear(data: ClearBought, source: AppSourceDep) -> CountRead:
    return CountRead(count=await service.clear_bought(data.shopping_list_id, source))


@router.patch("/{id}", response_model=ItemRead)
async def update(id: UUID, data: ItemUpdate, source: AppSourceDep) -> ItemRead:
    return await service.update_item(id, data, source)


@router.delete("/{id}", status_code=204, response_class=Response, response_model=None)
async def delete(id: UUID, source: AppSourceDep) -> Response:
    await service.delete_item(id, source)
    return Response(status_code=204)
