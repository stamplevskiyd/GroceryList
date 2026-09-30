from typing import ClassVar

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    loc: list[str | int]
    message: str


class DomainError(Exception):
    code: ClassVar[str] = "domain_error"
    message: ClassVar[str] = "Ошибка операции"
    hint: ClassVar[str | None] = None

    def __init__(self, message: str | None = None, *, details: list[ErrorDetail] | None = None):
        super().__init__(message or self.message)
        self.details = details


class NotFoundError(DomainError):
    code = "not_found"
    message = "Объект не найден"


class ShoppingListNotFoundError(NotFoundError):
    code = "shopping_list_not_found"
    message = "Список покупок не найден"


class ItemNotFoundError(NotFoundError):
    code = "item_not_found"
    message = "Позиция не найдена — возможно, её уже удалили"
    hint = "Вызови get_shopping_list, чтобы получить актуальные id"


class TagNotFoundError(NotFoundError):
    code = "tag_not_found"
    message = "Тег не найден"
    hint = "Вызови list_tags, чтобы получить актуальные id"


class InvalidInputError(DomainError):
    code = "invalid_input"
    message = "Некорректные данные"


class ConflictError(DomainError):
    code = "conflict"
    message = "Данные уже существуют"
