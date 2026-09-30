from typing import Annotated, Literal

from pydantic import BaseModel, Field


class AppSource(BaseModel):
    kind: Literal["app"] = "app"
    device_id: str = Field(min_length=1)


class McpSource(BaseModel):
    kind: Literal["mcp"] = "mcp"
    client_id: str = Field(min_length=1)
    client_name: str = Field(min_length=1)


Source = Annotated[AppSource | McpSource, Field(discriminator="kind")]


class AppAttribution(BaseModel):
    kind: Literal["app"] = "app"


class McpAttribution(BaseModel):
    kind: Literal["mcp"] = "mcp"
    client_name: str


ItemSource = Annotated[AppAttribution | McpAttribution, Field(discriminator="kind")]


def item_source(source: Source) -> ItemSource:
    if isinstance(source, AppSource):
        return AppAttribution()
    return McpAttribution(client_name=source.client_name)
