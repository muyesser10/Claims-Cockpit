# scripts/create_user.py
"""CLI to provision a user for local dev/testing (S3-8).

No public registration endpoint exists on purpose — accounts are
provisioned out of band, by someone who already has DB access. Usage:

    python -m scripts.create_user --email operator@test.com --password secret123 --role operator
"""

from typing import Annotated

import typer

from api.database import SessionLocal
from api.models.db import User
from api.security import hash_password

app = typer.Typer()


@app.command()
def create_user(
    email: Annotated[str, typer.Option(help="Login email, must be unique")],
    password: Annotated[str, typer.Option(help="Plaintext password (hashed before storing)")],
    role: Annotated[str, typer.Option(help="e.g. operator or admin")] = "operator",
) -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing is not None:
            typer.echo(f"User {email} already exists (id={existing.id}), skipping.")
            raise typer.Exit(code=1)

        user = User(email=email, password_hash=hash_password(password), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        typer.echo(f"Created user {user.email} (id={user.id}, role={user.role})")
    finally:
        db.close()


if __name__ == "__main__":
    app()
