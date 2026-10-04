"""Protocol errors are independent of REST domain errors."""

from grocery.schemas.oauth import OAuthFailure


class OAuthError(Exception):
    def __init__(self, error: str, description: str) -> None:
        self.response = OAuthFailure(error=error, error_description=description)
        super().__init__(description)
