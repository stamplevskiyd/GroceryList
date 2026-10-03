"""SDK adapter for transport-independent PAT verification."""

from mcp.server.auth.provider import AccessToken

from grocery.db.session import unit_of_work
from grocery.services.auth.tokens import verify_bearer


class GroceryTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        async with unit_of_work():
            identity = await verify_bearer(token)
        if identity is None:
            return None
        return AccessToken(
            token=token,
            subject=str(identity.user_id),
            client_id=identity.client_id,
            scopes=identity.scopes,
            resource=identity.resource,
            claims={"client_name": identity.client_name},
        )
