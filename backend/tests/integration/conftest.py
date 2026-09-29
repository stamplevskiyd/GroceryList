"""Интеграционные тесты: каждый изолирован фикстурой db."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(db: None) -> None:
    return None
