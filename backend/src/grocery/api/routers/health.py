"""GET /api/health — публичный эндпоинт для деплоя и healthcheck (ADR-0015)."""

from fastapi import APIRouter, Response, status

from grocery.config import get_settings
from grocery.schemas.health import HealthRead
from grocery.services import health as health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthRead}},
)
async def health(response: Response) -> HealthRead:
    version = get_settings().app.version
    if not await health_service.database_is_available():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthRead(status="unavailable", version=version)
    return HealthRead(status="ok", version=version)
