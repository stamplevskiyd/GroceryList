from pydantic import BaseModel

from grocery.domain.errors import ErrorDetail


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None
