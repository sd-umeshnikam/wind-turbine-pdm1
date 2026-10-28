"""Operator commands that need shell access to the platform (break-glass, audited).

python -m wtpdm.api.manage reset-password <username>   # new password read from stdin
python -m wtpdm.api.manage list-users
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from wtpdm.api.security import hash_password
from wtpdm.db.models import AppUser, AuditLog
from wtpdm.db.session import session_scope

MIN_PASSWORD = 12


def reset_password(username: str, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"password must have at least {MIN_PASSWORD} characters")
    with session_scope() as s:
        user = s.scalars(select(AppUser).where(AppUser.username == username)).first()
        if user is None:
            raise SystemExit(f"no user {username}")
        user.password_hash, user.is_active = hash_password(password), True
        s.add(
            AuditLog(
                actor="system:manage",
                action="user.update",
                entity="user",
                entity_id=username,
                details={"password": "reset"},
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser(
        "reset-password", help="set a new password (read from stdin) and reactivate the user"
    )
    reset.add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args()

    if args.command == "reset-password":
        password = (
            getpass.getpass("New password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        )
        reset_password(args.username, password)
        print(f"password of {args.username} reset")
    else:
        with session_scope() as s:
            for u in s.scalars(select(AppUser).order_by(AppUser.username)):
                print(f"{u.username:<24} {u.role.value:<9} {'active' if u.is_active else 'deactivated'}")


if __name__ == "__main__":
    main()
