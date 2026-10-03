"""Thin MCP adapters over the shared shopping service."""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp.types import ToolAnnotations
from pydantic import Field

from grocery.mcp_server.middleware import domain_errors, get_mcp_source
from grocery.schemas.common import CountRead, Name
from grocery.schemas.items import (
    AddItemResult,
    AddItems,
    ItemCreate,
    ItemRead,
    ItemUpdate,
)
from grocery.schemas.tags import TagUsageRead
from grocery.services import shopping_list_service as service


async def selected_list(shopping_list_id: UUID | None) -> UUID:
    return (
        shopping_list_id
        if shopping_list_id is not None
        else await service.get_default_shopping_list_id()
    )


class UpdateItemArguments(ItemUpdate, ArgModelBase):
    """Flat MCP input inherits every field and validator of the REST patch."""

    id: UUID
    shopping_list_id: UUID | None = None

    def model_dump_one_level(self) -> dict[str, Any]:
        # SDK kwargs are heterogeneous by definition. Build the shared patch from
        # only supplied fields; no manual list of patch fields or signature defaults.
        data = ItemUpdate.model_validate(
            self.model_dump(
                exclude={"id", "shopping_list_id"},
                exclude_unset=True,
                exclude_computed_fields=True,
            )
        )
        return {"id": self.id, "shopping_list_id": self.shopping_list_id, "data": data}


def build_tools() -> list[Tool]:
    tools: list[Tool] = []

    # SDK introspects heterogeneous function signatures, so its Tool factory takes Any.
    def tool(*, annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            registered = Tool.from_function(fn, annotations=annotations)
            if fn.__name__ == "update_item":
                registered.fn_metadata.arg_model = UpdateItemArguments
            registered.fn_metadata.arg_model.model_config["extra"] = "forbid"
            registered.fn_metadata.arg_model.model_rebuild(force=True)
            registered.parameters = registered.fn_metadata.arg_model.model_json_schema()
            tools.append(registered)
            return fn

        return register

    @tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
    @domain_errors
    async def get_shopping_list(
        shopping_list_id: UUID | None = None, tag: Name | None = None, include_bought: bool = False
    ) -> list[ItemRead]:
        """Получить список перед добавлением. tag — точное имя тега.

        Купленные скрыты по умолчанию.
        """
        return await service.get_items(
            await selected_list(shopping_list_id), include_bought=include_bought, tag=tag
        )

    @tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
    @domain_errors
    async def list_tags(shopping_list_id: UUID | None = None) -> list[TagUsageRead]:
        """Получить существующие теги и число позиций; переиспользуй названия при добавлении."""
        return await service.list_tags(await selected_list(shopping_list_id))

    @tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        )
    )
    @domain_errors
    async def add_items(
        items: Annotated[list[ItemCreate], Field(min_length=1)],
        shopping_list_id: UUID | None = None,
    ) -> list[AddItemResult]:
        """Добавить пачку атомарно: дубликаты объединяются с суммированием.

        Результат по позиции: created/merged.
        """
        return await service.add_items(
            AddItems(shopping_list_id=await selected_list(shopping_list_id), items=items),
            get_mcp_source(),
        )

    @tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
    @domain_errors
    async def update_item(
        id: UUID,
        data: ItemUpdate,
        shopping_list_id: UUID | None = None,
    ) -> ItemRead:
        """Изменить позицию выбранного списка.

        Пропуск сохраняет поле, null очищает quantity/unit/note, tags=[] очищает теги.
        """
        return await service.update_item(
            id, data, get_mcp_source(), shopping_list_id=await selected_list(shopping_list_id)
        )

    @tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        )
    )
    @domain_errors
    async def set_bought(
        ids: Annotated[list[UUID], Field(min_length=1)],
        bought: bool,
        shopping_list_id: UUID | None = None,
    ) -> list[ItemRead]:
        """Отметить позиции купленными или вернуть в список. Повтор не меняет состояние."""
        return await service.set_bought(
            await selected_list(shopping_list_id), ids, bought, get_mcp_source()
        )

    @tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        )
    )
    @domain_errors
    async def remove_items(
        shopping_list_id: UUID | None = None,
        ids: Annotated[list[UUID], Field(min_length=1)] | None = None,
        tag: Name | None = None,
    ) -> CountRead:
        """Удалить позиции, включая купленные.

        Укажи ровно один селектор: непустые ids или tag.
        """
        return CountRead(
            count=await service.remove_items(
                await selected_list(shopping_list_id), get_mcp_source(), ids=ids, tag=tag
            )
        )

    return tools
