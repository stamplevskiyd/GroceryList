"""Manual OAuth acceptance: print a link, receive loopback callback, verify MCP.

Run: uv run --project backend python scripts/check_oauth_browser.py https://your-host
The browser is opened by the user. Tokens stay in memory and are revoked on exit.
"""

import argparse
import asyncio
import base64
import hashlib
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def verify_mcp(origin: str, token: str) -> None:
    async with (
        httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False) as http,
        Client(streamable_http_client(origin + "/mcp", http_client=http), cache=None) as client,
    ):
        tools = await client.list_tools()
        if len(tools.tools) != 6:
            raise RuntimeError("Unexpected MCP tool list")
        result = await client.call_tool("get_shopping_list", {})
        if result.is_error:
            raise RuntimeError("MCP call failed")
        print("MCP handshake and reading the shopping list: OK (contents are not printed)")


def run(origin: str) -> None:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    callback: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            # Callback query contains an authorization code; never log it.
            return None

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            valid = (
                parts.path == "/callback"
                and query.get("state") == [state]
                and query.get("iss") == [origin]
            )
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if not valid:
                self.wfile.write(b"Invalid callback")
                return
            callback.update({key: values[0] for key, values in query.items()})
            self.wfile.write("Решение получено. Вернитесь в терминал.".encode())

    with (
        HTTPServer(("127.0.0.1", 0), Handler) as server,
        httpx.Client(base_url=origin, timeout=10, trust_env=False) as http,
    ):
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        registered = http.post(
            "/oauth/register",
            json={
                "client_name": "Ручная проверка GroceryList",
                "redirect_uris": [redirect],
                "token_endpoint_auth_method": "none",
            },
        )
        registered.raise_for_status()
        client_id = str(registered.json()["client_id"])
        params = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "resource": origin + "/mcp",
            "scope": "shopping_list offline_access",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        print("Откройте ссылку вручную в браузере, войдите и подтвердите доступ:\n")
        print(origin + "/oauth/authorize?" + urlencode(params), flush=True)
        deadline = time.monotonic() + 600
        server.timeout = 1
        while not callback and time.monotonic() < deadline:
            server.handle_request()
        if not callback:
            raise RuntimeError("Ожидание истекло. Запустите проверку заново.")
        if callback.get("error") or not callback.get("code"):
            raise RuntimeError("Доступ отклонён или код не получен.")
        response = http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": callback["code"],
                "redirect_uri": redirect,
                "code_verifier": verifier,
                "resource": origin + "/mcp",
            },
        )
        response.raise_for_status()
        pair = response.json()
        original_refresh = str(pair["refresh_token"])
        try:
            asyncio.run(verify_mcp(origin, str(pair["access_token"])))
            refreshed = http.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": original_refresh,
                    "resource": origin + "/mcp",
                },
            )
            refreshed.raise_for_status()
            print("Refresh rotation: OK")
        finally:
            # Even the old rotated refresh token revokes its entire family.
            revoked = http.post(
                "/oauth/revoke",
                data={"client_id": client_id, "token": original_refresh},
            )
            revoked.raise_for_status()
            print("Test connection revoked")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "origin", help="HTTPS origin of the deployed/local backend and consent page"
    )
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        parser.error("Use an HTTPS origin without path, query or credentials")
    run(origin)
