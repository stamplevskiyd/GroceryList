"""Shared REST error responses and exception translation (ADR-0012)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from grocery.domain.errors import (
    ConflictError,
    DomainError,
    ErrorDetail,
    InvalidInputError,
    NotFoundError,
)
from grocery.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ErrorResponse} for status in (404, 409, 422, 500)
}

_DOMAIN_STATUS_CODES: dict[type[DomainError], int] = {
    NotFoundError: 404,
    InvalidInputError: 422,
    ConflictError: 409,
}


def _error_response(status_code: int, error: ErrorResponse) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json", exclude_none=True),
    )


def _internal_error_response(exc: Exception) -> JSONResponse:
    logger.error("internal_error", exc_info=exc)
    return _error_response(
        500,
        ErrorResponse(code="internal_error", message="Внутренняя ошибка"),
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = next(
            (
                status
                for error_type, status in _DOMAIN_STATUS_CODES.items()
                if isinstance(exc, error_type)
            ),
            None,
        )
        if status_code is None:
            return _internal_error_response(exc)
        logger.info(exc.code)
        return _error_response(
            status_code,
            ErrorResponse(code=exc.code, message=str(exc), details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ErrorDetail(loc=list(error["loc"]), message=error["msg"]) for error in exc.errors()
        ]
        return _error_response(
            422,
            ErrorResponse(code="invalid_request", message="Некорректный запрос", details=details),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _internal_error_response(exc)
