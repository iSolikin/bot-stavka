"""
Миграция: добавляет колонку `tier` в таблицу matches (если её нет)
и проставляет тиры всем существующим матчам по названию турнира.

Запуск:  python migrate_add_tier.py
"""
import sqlite3

from collectors.tournament_tiers import get_tier

DB_PATH = "bot.db"


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()

    # 1. Добавляем колонку tier, если её ещё нет
    cols = [r[1] for r in c.execute("PRAGMA table_info(matches)")]
    if "tier" not in cols:
        print("Добавляю колонку tier...")
        c.execute("ALTER TABLE matches ADD COLUMN tier INTEGER DEFAULT 3")
        db.commit()
        print("  колонка tier добавлена")
    else:
        print("Колонка tier уже есть")

    # 2. Бэкфилл тиров по названию турнира
    rows = c.execute("SELECT id, tournament, game FROM matches").fetchall()
    print(f"Обрабатываю {len(rows)} матчей...")

    updated = 0
    tier_counts = {1: 0, 2: 0, 3: 0}
    for mid, tournament, game in rows:
        tier = get_tier(tournament or "", game or "")
        c.execute("UPDATE matches SET tier = ? WHERE id = ?", (tier, mid))
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        updated += 1

    db.commit()
    print(f"Обновлено {updated} матчей")
    print(f"  T1: {tier_counts[1]}  T2: {tier_counts[2]}  T3: {tier_counts[3]}")

    # 3. Сводка по доте
    print("\nDota2 завершённые матчи по тирам:")
    for r in c.execute(
        "SELECT tier, COUNT(*) FROM matches WHERE game='dota2' AND status='finished' GROUP BY tier ORDER BY tier"
    ):
        print(f"  T{r[0]}: {r[1]}")

    db.close()


if __name__ == "__main__":
    main()
