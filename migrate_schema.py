"""
Универсальная миграция: сверяет SQLAlchemy-модели с реальной схемой SQLite
и добавляет все недостающие колонки через ALTER TABLE ADD COLUMN.
Затем проставляет tier всем матчам по названию турнира.

Запуск:  python migrate_schema.py
"""
import sqlite3

from sqlalchemy import Integer, Float, Boolean, String, Text, DateTime, JSON, BigInteger

import db.models as models
from db.models import Base
from collectors.tournament_tiers import get_tier

DB_PATH = "bot.db"


def _sqlite_type(col) -> str:
    """Маппинг SQLAlchemy типа -> SQLite affinity."""
    t = col.type
    if isinstance(t, (Integer, BigInteger, Boolean)):
        return "INTEGER"
    if isinstance(t, Float):
        return "REAL"
    if isinstance(t, (String, Text)):
        return "TEXT"
    if isinstance(t, DateTime):
        return "TEXT"
    if isinstance(t, JSON):
        return "TEXT"
    return "TEXT"


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()

    existing_tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}

    total_added = 0
    for table in Base.metadata.sorted_tables:
        name = table.name
        if name not in existing_tables:
            print(f"[создаю таблицу] {name}")
            ddl_cols = []
            for col in table.columns:
                coltype = _sqlite_type(col)
                pk = " PRIMARY KEY" if col.primary_key else ""
                ddl_cols.append(f"{col.name} {coltype}{pk}")
            c.execute(f"CREATE TABLE {name} ({', '.join(ddl_cols)})")
            db.commit()
            continue

        db_cols = {r[1] for r in c.execute(f"PRAGMA table_info({name})")}
        for col in table.columns:
            if col.name not in db_cols:
                coltype = _sqlite_type(col)
                default = ""
                if col.default is not None and getattr(col.default, "arg", None) is not None:
                    arg = col.default.arg
                    if isinstance(arg, (int, float)):
                        default = f" DEFAULT {arg}"
                    elif isinstance(arg, str):
                        default = f" DEFAULT '{arg}'"
                c.execute(f"ALTER TABLE {name} ADD COLUMN {col.name} {coltype}{default}")
                print(f"  + {name}.{col.name} ({coltype}{default})")
                total_added += 1
        db.commit()

    print(f"\nДобавлено колонок: {total_added}")

    # Бэкфилл tier
    rows = c.execute("SELECT id, tournament, game FROM matches").fetchall()
    tier_counts = {1: 0, 2: 0, 3: 0}
    for mid, tournament, game in rows:
        tier = get_tier(tournament or "", game or "")
        c.execute("UPDATE matches SET tier = ? WHERE id = ?", (tier, mid))
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    db.commit()
    print(f"Tier backfill: T1={tier_counts[1]} T2={tier_counts[2]} T3={tier_counts[3]}")

    db.close()


if __name__ == "__main__":
    main()
