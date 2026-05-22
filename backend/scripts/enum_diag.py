"""Quick diagnostic — answers: (1) which DB are we on (host only, no creds),
(2) what alembic version does it think it's at, (3) what enum values does
email_status actually contain on this DB."""
from sqlalchemy import create_engine, text
from urllib.parse import urlparse

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    parsed = urlparse(settings.database_url)
    # Print HOST+DB only — never the password.
    print(f"DB host: {parsed.hostname}:{parsed.port}  db={parsed.path.lstrip('/')}")

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"alembic_version on this DB: {version}")

        enum_rows = conn.execute(
            text(
                "SELECT enumlabel FROM pg_enum "
                "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                "WHERE pg_type.typname = 'email_status' "
                "ORDER BY enumsortorder"
            )
        ).all()
        labels = [r[0] for r in enum_rows]
        print(f"email_status values: {labels}")
        print(f"  has 'deleted'? {'deleted' in labels}")
        print(f"  has 'spam'?    {'spam' in labels}")


if __name__ == "__main__":
    main()
