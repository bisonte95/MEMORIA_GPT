# create_db.py - crea memoria.db a partir de schema.sql usando sqlite3 incluido en Python
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema.sql"
DB_PATH = BASE_DIR / "memoria.db"


def main() -> None:
    """Leer schema.sql y aplicarlo sobre memoria.db."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"No encuentro {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema_sql)
        conn.commit()

    print(f"Esquema aplicado en {DB_PATH}")


if __name__ == "__main__":
    main()
