"""Административные команды: python -m grocery create-user USERNAME."""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from grocery.config import get_settings
from grocery.db.session import configure_engine, dispose_engine, unit_of_work
from grocery.domain.errors import DomainError
from grocery.services.auth import create_user


async def create_user_command(username: str, password: str) -> int:
    try:
        async with unit_of_work():
            user = await create_user(username, password)
    except DomainError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Создан пользователь {user.username} и список «Покупки»")
    return 0


async def _run_create_user(username: str, password: str) -> int:
    configure_engine(str(get_settings().db.url))
    try:
        return await create_user_command(username, password)
    finally:
        await dispose_engine()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m grocery")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Создать пользователя и его список покупок")
    create.add_argument("username", help="Логин")
    args = parser.parse_args(argv)
    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Повторите пароль: "):
        print("Пароли не совпадают", file=sys.stderr)
        return 1
    return asyncio.run(_run_create_user(args.username, password))


if __name__ == "__main__":
    sys.exit(main())
