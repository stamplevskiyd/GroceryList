import pytest

from grocery.services.auth.oauth_errors import OAuthError
from grocery.services.auth.oauth_urls import redirect_matches, validate_redirect


@pytest.mark.parametrize(
    "uri",
    [
        "https://client.example/callback",
        "http://localhost:8888/cb",
        "http://127.0.0.1:8888/cb",
        "http://[::1]:8888/cb",
    ],
)
def test_redirect_allowed(uri: str) -> None:
    validate_redirect(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "http://client.example/cb",
        "javascript:alert(1)",
        "https://user:pass@client.example/cb",
        "https://client.example/cb#fragment",
        "//evil.test",
        "https://evil.test\\@good.test/cb",
        "https://good.test\n.evil.test/cb",
        "http://127.0.0.1.evil.test/cb",
        "https://client.example/cb?code=old",
        "https://client.example:invalid/cb",
    ],
)
def test_redirect_refused(uri: str) -> None:
    with pytest.raises(OAuthError):
        validate_redirect(uri)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("http://127.0.0.1:1000/cb", "http://127.0.0.1:2000/cb", True),
        ("http://[::1]:1000/cb", "http://[::1]:2000/cb", True),
        ("http://localhost:1000/cb", "http://127.0.0.1:1000/cb", False),
        ("https://client.example:443/cb", "https://client.example/cb", False),
        ("http://localhost:1/cb?a=1", "http://localhost:2/cb?a=2", False),
        ("http://localhost:1/cb", "http://localhost:2/other", False),
    ],
)
def test_only_loopback_port_may_differ(a: str, b: str, expected: bool) -> None:
    assert redirect_matches(a, b) is expected
