"""Пакеты слоёв из ADR-0014 существуют и импортируются."""

import importlib

import pytest

LAYERS = [
    "grocery.api",
    "grocery.mcp_server",
    "grocery.services",
    "grocery.db",
    "grocery.db.repositories",
    "grocery.db.models",
    "grocery.schemas",
    "grocery.domain",
]


@pytest.mark.parametrize("module", LAYERS)
def test_layer_package_imports(module: str) -> None:
    assert importlib.import_module(module).__name__ == module
