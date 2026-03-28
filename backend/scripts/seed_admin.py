"""
Seed script — creates the initial admin (Jane) account.

Run once after `alembic upgrade head`:

    cd backend
    python scripts/seed_admin.py

Reads ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD from environment / .env.
"""
import os
import sys
from pathlib import Path

# Allow importing from app/ when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from app.config import get_settings
from app.database import SessionLocal
from app.models.user import UserRole
from app.services.auth import create_user, get_user_by_email


def main() -> None:
    settings = get_settings()

    email = settings.admin_email
    name = settings.admin_name
    password = settings.admin_password

    if not password:
        print("ERROR: ADMIN_PASSWORD is not set in .env. Aborting.")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = get_user_by_email(db, email)
        if existing:
            print(f"Admin user already exists: {email} (id={existing.id})")
            return

        user = create_user(
            db,
            email=email,
            name=name,
            password=password,
            role=UserRole.admin,
        )
        db.commit()
        print(f"Created admin user: {email} (id={user.id})")
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
