from uuid import UUID

from pydantic import BaseModel, computed_field

from grocery.domain.normalization import normalize_name
from grocery.schemas.items import Name, TagRead


class TagName(BaseModel):
    name: Name

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_normalized(self) -> str:
        return normalize_name(self.name)


class TagCreate(TagName):
    shopping_list_id: UUID


class TagUpdate(TagName):
    pass


class TagUsageRead(TagRead):
    open_count: int
