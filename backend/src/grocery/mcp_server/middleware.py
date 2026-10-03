"""Commit-before-result tool boundary; SDK error results must roll back."""

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from uuid import UUID

from mcp.server import ServerRequestContext
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, HandlerResult
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from grocery.db.session import unit_of_work
from grocery.domain.errors import DomainError
from grocery.schemas.sources import McpSource
from grocery.services.auth import acting_as
from grocery.services.auth.errors import AuthError
from grocery.services.auth.tokens import resolve_bearer_user

logger = logging.getLogger(__name__)


def get_mcp_source() -> McpSource:
    token = get_access_token()
    if token is None or token.subject is None:
        raise AuthError("Требуется вход")
    return McpSource(client_id=token.client_id, client_name=(token.claims or {})["client_name"])


def domain_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    # SDK catches exceptions before returning to middleware. Translate at a shared
    # handler boundary so DomainError hints survive; never duplicate this in tools.
    @wraps(fn)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            logger.info("MCP domain error: %s", exc.code)
            message = str(exc)
            if exc.hint:
                message += "\n" + exc.hint
            if exc.details:
                message += "\n" + "; ".join(
                    f"{'.'.join(map(str, detail.loc))}: {detail.message}" for detail in exc.details
                )
            raise ToolError(message) from exc
        except Exception:
            # Keep exception details on the server, not in a tool result.
            logger.exception("MCP handler failed")
            raise ToolError("Внутренняя ошибка") from None

    return wrapped


class _FailedCallError(Exception):
    def __init__(self, result: HandlerResult):
        self.result = result


def error_result(message: str) -> CallToolResult:
    return CallToolResult(is_error=True, content=[TextContent(type="text", text=message)])


async def tool_unit_of_work(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
    if ctx.method != "tools/call":
        return await call_next(ctx)
    try:
        token = get_access_token()
        if token is None or token.subject is None:
            return error_result("Требуется вход")
        async with unit_of_work():
            with acting_as(await resolve_bearer_user(UUID(token.subject))):
                result = await call_next(ctx)
                # SDK 2.2 serializes the handler result before returning through
                # middleware. Support both the wire dict and a model result.
                failed = (
                    result.get("isError") is True
                    if isinstance(result, dict)
                    else isinstance(result, CallToolResult) and result.is_error
                )
                if failed:
                    raise _FailedCallError(result)
        # unit_of_work has committed before a success can leave this boundary.
        return result
    except _FailedCallError as exc:
        return exc.result
    except AuthError:
        return error_result("Требуется вход")
    except Exception:
        logger.exception("MCP transaction failed")
        return error_result("Внутренняя ошибка")
