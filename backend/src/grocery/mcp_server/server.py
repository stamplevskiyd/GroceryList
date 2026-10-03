"""Resource-server assembly and public metadata (ADR-0010)."""

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from grocery.config import AppSettings
from grocery.mcp_server.instructions import INSTRUCTIONS
from grocery.mcp_server.middleware import tool_unit_of_work
from grocery.mcp_server.tools import build_tools
from grocery.mcp_server.verifier import GroceryTokenVerifier


def create_mcp(settings: AppSettings) -> tuple[MCPServer, Starlette]:
    server = MCPServer(
        "GroceryList",
        log_level=settings.log_level,
        instructions=INSTRUCTIONS,
        tools=build_tools(),
        token_verifier=GroceryTokenVerifier(),
        middleware=[tool_unit_of_work],
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.origin),
            resource_server_url=AnyHttpUrl(settings.mcp_url),
            required_scopes=["shopping_list"],
            validate_token_resource=True,
        ),
    )
    # netloc includes the configured port; no wildcard Host or Origin.
    authority = settings.origin.split("//", 1)[1]
    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[authority],
            allowed_origins=[settings.origin],
        ),
    )

    metadata_route = next(
        route
        for route in app.routes
        if isinstance(route, Route) and route.path == "/.well-known/oauth-protected-resource/mcp"
    )
    app.router.routes.insert(
        0, Route("/.well-known/oauth-protected-resource", metadata_route.endpoint)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.origin],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "Mcp-Protocol-Version",
            "Last-Event-ID",
        ],
        expose_headers=["Mcp-Session-Id", "WWW-Authenticate", "Mcp-Protocol-Version"],
    )
    return server, app
