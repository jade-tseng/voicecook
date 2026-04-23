import asyncio
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


async def run_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   text        PRIMARY KEY,
            applied_at timestamptz DEFAULT now()
        )
    """)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for sql_file in sql_files:
        already_applied = await conn.fetchval(
            "SELECT filename FROM schema_migrations WHERE filename = $1",
            sql_file.name,
        )
        if already_applied:
            continue
        async with conn.transaction():
            await conn.execute(sql_file.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES ($1)",
                sql_file.name,
            )
        print(f"[migrate] applied {sql_file.name}")


async def _main() -> None:
    import os
    url = os.environ.get(
        "DATABASE_URL", "postgresql://cookbot:cookbot@localhost:5432/cookbot"
    )
    conn = await asyncpg.connect(url)
    try:
        await run_migrations(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
