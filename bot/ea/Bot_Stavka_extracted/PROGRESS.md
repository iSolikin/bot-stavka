# Bot_Stavka — Прогресс разработки

> Последнее обновление: всё собрано, готово к запуску

---

## Что сделано

### ✅ Фаза 1 — Фундамент

| Файл | Что делает |
|---|---|
| `requirements.txt` | Все зависимости: aiogram, sqlalchemy, aiosqlite, playwright, apscheduler, redis и др. |
| `.env` | Уже заполнен: BOT_TOKEN, ADMIN_ID, SQLite БД |
| `config.py` | Читает `.env`. Поддерживает DATABASE_URL (SQLite или PostgreSQL), ODDS_API_KEY, FACEIT_API_KEY |
| `db/models.py` | Таблицы: teams, players, matches, patches, telegram_messages, telegram_channels, users |
| `db/database.py` | Async движок. Автоматически выбирает StaticPool для SQLite, NullPool для PostgreSQL |

---

### ✅ Фаза 2 — Сборщики данных

| Файл | Что делает |
|---|---|
| `collectors/opendota.py` | OpenDota API — команды и матчи Dota2 |
| `collectors/hltv.py` | HLTV через Playwright — матчи и рейтинги CS2 |
| `collectors/liquipedia.py` | Liquipedia API — турниры и составы |
| `collectors/patches.py` | Патч-ноуты CS2 (Steam) и Dota2 |
| `collectors/telegram_collector.py` | Telethon — читает каналы, парсит упоминания команд |
| `collectors/faceit.py` | ⭐ FACEIT API — K/D, HS%, ELO, уровень игроков CS2 |
| `collectors/odds.py` | ⭐ The Odds API — кэфы букмекеров на матчи |
| `collectors/rating.py` | ⭐ ELO-рейтинг команд по истории матчей из БД |

---

### ✅ Фаза 3 — Планировщик

| Джоб | Расписание | Что делает |
|---|---|---|
| opendota_sync | каждые 2ч | Матчи и команды Dota2 |
| hltv_sync | каждые 2ч | Матчи и рейтинги CS2 |
| liquipedia_sync | каждые 6ч | Турниры и составы |
| patches_sync | 03:00 UTC | Патч-ноуты |
| telegram_sync | каждые 60 сек | Новые сообщения в каналах |
| ratings_recalc | ⭐ каждые 12ч | Пересчёт ELO-рейтингов |
| faceit_sync | ⭐ каждые 6ч | Обогащение игроков CS2 через FACEIT |

---

### ✅ Фаза 4 — Агрегатор и Анализатор

| Файл | Что делает |
|---|---|
| `aggregator/aggregator.py` | Объединяет данные из всех источников. Нормализация названий (50+ алиасов). Форма, H2H, игроки, патч, Telegram |
| `analyzer/analyzer.py` | Текстовые отчёты по командам, матчам, игрокам, патчам. Полный анализ матча с предиктом |
| `analyzer/predictor.py` | ⭐ ELO-предикт победителя: форма (40%) + рейтинг (30%) + H2H (30%). Если есть кэфы — добавляет их как 4-й фактор |

---

### ✅ Фаза 5 — Telegram-бот

| Файл | Что делает |
|---|---|
| `bot/handlers/start.py` | `/start` с главным меню, `/help`, callbacks `back_main` и `help` |
| `bot/handlers/matches.py` | `/upcoming` и `/match` — список матчей с inline-кнопками, анализ по клику |
| `bot/handlers/teams.py` | `/team`, `/player`, `/patch` |
| `bot/handlers/admin.py` | `/admin` — управление каналами, статус системы |
| `bot/keyboards/__init__.py` | `main_menu()` и `back_to_menu()` |
| `bot/formatters/telegram_format.py` | Экранирование MarkdownV2, разбивка длинных сообщений |
| `cache/redis_cache.py` | Redis кэш для team, match, player, patch, upcoming отчётов |

---

## Структура файлов

```
Bot_Stavka_extracted/
├── bot/
│   ├── formatters/telegram_format.py   ✅
│   ├── handlers/
│   │   ├── __init__.py                 ✅
│   │   ├── admin.py                    ✅
│   │   ├── matches.py                  ✅ inline-кнопки
│   │   ├── start.py                    ✅ главное меню
│   │   └── teams.py                    ✅ /team /player /patch
│   └── keyboards/__init__.py           ✅ main_menu, back_to_menu
├── collectors/
│   ├── faceit.py                       ✅ FACEIT API
│   ├── hltv.py                         ✅ Playwright
│   ├── liquipedia.py                   ✅
│   ├── odds.py                         ✅ кэфы букмекеров
│   ├── opendota.py                     ✅
│   ├── patches.py                      ✅
│   ├── rating.py                       ✅ ELO-рейтинг
│   └── telegram_collector.py           ✅
├── aggregator/aggregator.py            ✅ 50+ алиасов команд
├── analyzer/
│   ├── analyzer.py                     ✅ полный анализ + предикт
│   └── predictor.py                    ✅ ELO-предикт
├── cache/redis_cache.py                ✅ team/match/player/patch
├── db/
│   ├── database.py                     ✅ SQLite + PostgreSQL
│   └── models.py                       ✅
├── scheduler/scheduler.py              ✅ 7 джобов
├── .env                                ✅ заполнен
├── config.py                           ✅ FACEIT + ODDS ключи
├── main.py                             ✅
└── requirements.txt                    ✅
```

---

## Запуск прямо сейчас

```bash
cd Bot_Stavka_extracted
pip install -r requirements.txt
python main.py
```

Бот запустится на SQLite — PostgreSQL и Redis не нужны для старта.

---

## Следующие задачи

| Приоритет | Задача |
|---|---|
| 🔴 | Получить FACEIT API ключ → developers.faceit.com (бесплатно) |
| 🔴 | Получить Odds API ключ → the-odds-api.com (бесплатно, 500 запросов/мес) |
| 🟡 | Добавить каналы через `/admin add_channel @channel` |
| 🟡 | Заполнить TG_API_ID / TG_API_HASH для Telethon (my.telegram.org) |
| 🟢 | Перейти на PostgreSQL когда будет сервер |
| 🟢 | Добавить уведомления о начале матчей |
| 🟢 | Расширить словарь алиасов команд в aggregator.py |

---

## Известные ограничения

- **HLTV** — может менять HTML, тогда обновить селекторы в `collectors/hltv.py`
- **Liquipedia** — rate limit 30 сек между запросами
- **Telethon** — при первом запуске попросит SMS-код (создаст `.session` файл)
- **Odds API** — 500 запросов/месяц на бесплатном тарифе, используем экономно
