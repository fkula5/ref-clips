"""Usage: python -m app.create_admin
An existing e-mail is promoted to admin and gets a new password, which is also the way to recover
admin access.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app import accounts
from app.db import SessionLocal
from app.initdb import init_db


def _ask(prompt: str, value: str | None) -> str:
    return value if value else input(prompt).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zakłada konto administratora ref-clips.")
    parser.add_argument("--email", help="adres e-mail (login)")
    parser.add_argument("--name", help="imię i nazwisko")
    parser.add_argument("--password", help="hasło (bez tego polecenie zapyta bez wyświetlania)")
    args = parser.parse_args(argv)

    email = _ask("E-mail: ", args.email)
    name = _ask("Imię i nazwisko: ", args.name)
    password = args.password
    if not password:
        password = getpass.getpass("Hasło: ")
        if password != getpass.getpass("Powtórz hasło: "):
            print("Hasła nie są takie same.", file=sys.stderr)
            return 1

    init_db()
    with SessionLocal() as db:
        try:
            user, created = accounts.ensure_admin(db, email=email, name=name or email,
                                                  password=password)
        except accounts.AccountError as exc:
            print(f"Błąd: {exc}", file=sys.stderr)
            return 1
    print(f"{'Utworzono' if created else 'Zaktualizowano'} administratora: {user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
