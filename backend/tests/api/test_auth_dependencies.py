"""Authenticated context lifetime and dependency ordering."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from grocery.db.session import get_current_session
from grocery.services import auth
from grocery.services.auth.errors import AuthError


class ProbeBody(BaseModel):
    required: int


def add_protected_probe(app: FastAPI) -> None:
    from grocery.api.deps import AppSourceDep, Authenticated

    router = APIRouter(dependencies=[Authenticated])

    @router.post("/probe/source")
    async def source_probe(body: ProbeBody, source: AppSourceDep) -> dict[str, str]:
        assert get_current_session() is not None
        return {"username": auth.get_current_user().username, "device_id": source.device_id}

    @router.get("/probe/fail")
    async def failing_probe() -> None:
        assert auth.get_current_user().username == "anna"
        raise RuntimeError("forced endpoint exception")

    app.include_router(router)


# Exercise each invalid input and both authentication branches without a Cartesian product.
@pytest.mark.parametrize(
    ("body", "headers", "cookie"),
    [
        pytest.param({}, {"X-Device-Id": "phone"}, None, id="missing-body"),
        pytest.param({"required": "invalid"}, {"X-Device-Id": "phone"}, None, id="invalid-body"),
        pytest.param({"required": 1}, {}, None, id="missing-header"),
        pytest.param({"required": 1}, {"X-Device-Id": "   "}, "random-token", id="blank-header"),
        pytest.param({"required": 1}, {"X-Device-Id": "x" * 129}, "random-token", id="long-header"),
        pytest.param({}, {}, "random-token", id="invalid-body-and-header"),
    ],
)
async def test_authentication_precedes_header_and_body_validation(
    app: FastAPI,
    client: httpx.AsyncClient,
    body: dict[str, object],
    headers: dict[str, str],
    cookie: str | None,
) -> None:
    add_protected_probe(app)
    if cookie is not None:
        client.cookies.set("__Host-gl_session", cookie)
    response = await client.post("/probe/source", headers=headers, json=body)
    assert response.status_code == 401
    assert response.json() == {"code": "not_authenticated", "message": "Требуется вход"}
    response = await client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


@pytest.mark.parametrize("device_id", [None, "", "   ", "x" * 129])
async def test_authenticated_mutation_requires_device_header(
    app: FastAPI, client: httpx.AsyncClient, registered_user: None, device_id: str | None
) -> None:
    add_protected_probe(app)
    assert (
        await client.post(
            "/api/auth/login",
            headers={"X-Device-Id": "phone"},
            json={"username": "anna", "password": "test-password"},
        )
    ).status_code == 200
    response = await client.post(
        "/probe/source",
        headers={} if device_id is None else {"X-Device-Id": device_id},
        json={"required": 1},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert ["header", "X-Device-Id"] in [detail["loc"] for detail in response.json()["details"]]
    response = await client.post(
        "/api/auth/logout", headers={} if device_id is None else {"X-Device-Id": device_id}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    with pytest.raises(AuthError):
        auth.get_current_user()


async def test_context_resets_after_requests_and_exception(
    app: FastAPI, client: httpx.AsyncClient, registered_user: None
) -> None:
    add_protected_probe(app)
    await client.post(
        "/api/auth/login",
        headers={"X-Device-Id": "phone"},
        json={"username": "anna", "password": "test-password"},
    )
    response = await client.post(
        "/probe/source",
        headers={"X-Device-Id": " laptop "},
        json={"required": 1},
    )
    assert response.status_code == 200
    assert response.json() == {"username": "anna", "device_id": "laptop"}
    with pytest.raises(AuthError):
        auth.get_current_user()
    with pytest.raises(RuntimeError, match="Сессия БД не открыта"):
        get_current_session()
    with pytest.raises(RuntimeError, match="forced endpoint exception"):
        await client.get("/probe/fail")
    with pytest.raises(AuthError):
        auth.get_current_user()
    with pytest.raises(RuntimeError, match="Сессия БД не открыта"):
        get_current_session()
    client.cookies.clear()
    assert (await client.get("/api/me")).status_code == 401


async def test_lifespan_prewarms_passwords(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from grocery import main
    from grocery.services.auth import passwords

    # Reset state to exercise real startup initialization, without replacing the service.
    monkeypatch.setattr(passwords, "_dummy_hash", None)
    async with main.lifespan(app):
        assert passwords._dummy_hash is not None
