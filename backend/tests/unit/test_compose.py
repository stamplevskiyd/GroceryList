"""docker-compose.yml и тесты используют один образ Postgres (ADR-0011)."""

import re

from tests.support import POSTGRES_IMAGE, REPO_ROOT


def test_compose_postgres_image_matches_tests() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    images = re.findall(r"^\s*image:\s*(postgres:\S+)\s*$", compose, flags=re.MULTILINE)

    assert images == [POSTGRES_IMAGE, POSTGRES_IMAGE]
