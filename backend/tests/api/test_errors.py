import logging

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from grocery.db.models import User
from grocery.db.session import unit_of_work
from grocery.domain.errors import (
    ConflictError,
    DomainError,
    ErrorDetail,
    InvalidInputError,
    ItemNotFoundError,
    NotFoundError,
    ShoppingListNotFoundError,
    TagNotFoundError,
)
from tests.support_api import add_unit_of_work_probe_routes


class ValidationProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str
    required: int = Field(gt=0)


class UnmappedDomainError(DomainError):
    code = "private-diagnostic-code"


@pytest.fixture
def error_client(app: FastAPI) -> httpx.AsyncClient:
    # Starlette may re-raise an exception after sending its 500 response.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (NotFoundError, 404),
        (ShoppingListNotFoundError, 404),
        (ItemNotFoundError, 404),
        (TagNotFoundError, 404),
        (InvalidInputError, 422),
        (ConflictError, 409),
    ],
)
async def test_domain_errors_use_shared_contract(
    app: FastAPI,
    error_client: httpx.AsyncClient,
    error_type: type[DomainError],
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    @app.get("/probe/domain")
    async def probe() -> None:
        raise error_type("Уточнённое сообщение")

    with caplog.at_level(logging.INFO, logger="grocery.api.errors"):
        async with error_client:
            response = await error_client.get("/probe/domain")

    assert response.status_code == status
    assert response.json() == {"code": error_type.code, "message": "Уточнённое сообщение"}
    records = [record for record in caplog.records if record.name == "grocery.api.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].getMessage() == error_type.code


async def test_domain_details_are_preserved(app: FastAPI, error_client: httpx.AsyncClient) -> None:
    @app.get("/probe/domain")
    async def probe() -> None:
        raise InvalidInputError(
            details=[ErrorDetail(loc=["items", 3, "quantity"], message="Ошибка")]
        )

    async with error_client:
        response = await error_client.get("/probe/domain")
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_input",
        "message": InvalidInputError.message,
        "details": [{"loc": ["items", 3, "quantity"], "message": "Ошибка"}],
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"password": "private-test-value"}, "Field required"),
        (
            {"password": "private-test-value", "required": 0},
            "Input should be greater than 0",
        ),
    ],
)
async def test_validation_does_not_echo_password(
    app: FastAPI, client: httpx.AsyncClient, body: dict[str, object], message: str
) -> None:
    @app.post("/probe/validate")
    async def probe(body: ValidationProbe) -> None:
        return None

    response = await client.post("/probe/validate", json=body)
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_request",
        "message": "Некорректный запрос",
        "details": [{"loc": ["body", "required"], "message": message}],
    }
    assert "private-test-value" not in response.text
    assert "input" not in response.json()["details"][0]
    assert "ctx" not in response.json()["details"][0]


async def test_unexpected_error_hides_details_and_logs_traceback(
    app: FastAPI, error_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/probe/unexpected")
    async def probe() -> None:
        raise RuntimeError("private-internal-value")

    with caplog.at_level(logging.ERROR, logger="grocery.api.errors"):
        async with error_client:
            response = await error_client.get("/probe/unexpected")
    assert response.status_code == 500
    assert response.json() == {"code": "internal_error", "message": "Внутренняя ошибка"}
    assert "private-internal-value" not in response.text
    records = [record for record in caplog.records if record.name == "grocery.api.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


@pytest.mark.parametrize("error_type", [DomainError, UnmappedDomainError])
async def test_unmapped_domain_error_is_sanitized(
    app: FastAPI,
    error_client: httpx.AsyncClient,
    error_type: type[DomainError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    @app.get("/probe/unmapped-domain")
    async def probe() -> None:
        raise error_type(
            "private-diagnostic-message",
            details=[ErrorDetail(loc=["private"], message="private-diagnostic-detail")],
        )

    with caplog.at_level(logging.ERROR, logger="grocery.api.errors"):
        async with error_client:
            response = await error_client.get("/probe/unmapped-domain")
    assert response.status_code == 500
    assert response.json() == {"code": "internal_error", "message": "Внутренняя ошибка"}
    records = [record for record in caplog.records if record.name == "grocery.api.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


@pytest.mark.real_commits
async def test_commit_failure_uses_shared_error_contract(
    app: FastAPI, error_client: httpx.AsyncClient
) -> None:
    add_unit_of_work_probe_routes(app)
    async with unit_of_work() as session:
        session.add(User(username="anna", password_hash="h"))

    async with error_client:
        response = await error_client.post("/probe/users/anna")
    assert response.status_code == 500
    assert response.json() == {"code": "internal_error", "message": "Внутренняя ошибка"}


def test_reusable_responses_document_shared_errors(app: FastAPI) -> None:
    from grocery.api.errors import ERROR_RESPONSES
    from grocery.schemas.errors import ErrorResponse

    @app.get("/probe/responses", responses=ERROR_RESPONSES)
    async def probe() -> None:
        return None

    responses = app.openapi()["paths"]["/probe/responses"]["get"]["responses"]
    for status in (404, 409, 422, 500):
        assert ERROR_RESPONSES[status]["model"] is ErrorResponse
        assert responses[str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
