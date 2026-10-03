"""Enforce ADR-0004: only db/session.py commits or rolls back transactions."""

import ast
import sys
from pathlib import Path


def violations(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).as_posix() == "db/session.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"commit", "rollback"}
            ):
                errors.append(
                    f"{path}:{node.lineno}: {node.func.attr}() разрешён только в db/session.py"
                )
    return errors


if __name__ == "__main__":
    source_root = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1] / "backend/src/grocery"
    )
    found = violations(source_root)
    for error in found:
        print(error)
    raise SystemExit(bool(found))
