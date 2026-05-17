# Bot_Stavka — Прогресс разработки

> Последнее обновление: Фаза 1–5 завершена, деплой готов

---

## Что уже сделано

### ✅ Фаза 1 — Фундамент

| Файл | Что делает |
|---|---|
| `requirements.txt` | Все зависимости с зафиксированными версиями |
| `.env.example` | Шаблон конфига — скопировать в `.env` и заполнить |
| `config.py` | Читает `.env`, раздаёт настройки всем модулям |
| `db/models.py` | SQLAlchemy модели: `teams`, `players`, `matches`, `patches`, `telegram_messages`, `telegram_channels`, `users` |
| `db/database.py` | Async движок PostgreSQL, фабрика сессий, `init_db()` / `close_db()` |
| `db/__init__.py` | Экспорт всех моделей и функций БД |

---

### ✅ Фаза 2 — Сборщики данных

| Файл | Что делает |
|---|---|
| `collectors/opendota.py` | OpenDota API — команды Dota2, про-матчи, игроки. Бесплатный, без блокировок |
| `collectors/hltv.py` | HLTV парсер через Playwright (headless Chromium). Ротация User-Agent, задержки 3–6 сек |
| `collectors/liquipedia.py` | Liquipedia API + HTML парсинг. Матчи CS2 и Dota2, составы команд. Rate limit 30 сек |
| `collectors/patches.py` | Патч-ноуты CS2 (Steam API) и Dota2 (dota2.com) |
| `collectors/telegram_collector.py` | Telethon — читает сообщения из каналов, парсит упоминания команд/игроков по словарю |
| `collectors/__init__.py` | Экспорт всех `run_*_sync()` функций |

---

### ✅ Фаза 3 — Планировщик

| Файл | Что делает |
|---|---|
| `scheduler/scheduler.py` | APScheduler: матчи каждые 2ч, статистика каждые 6ч, патчи в 03:00 UTC, Telegram каждые 60 сек |
| `scheduler/__init__.py` | Экспорт `create_scheduler()` |

---

### ✅ Фаза 4 — Агрегатор и Анализатор

| Файл | Что делает |
|---|---|
| `aggregator/aggregator.py` | Объединяет данные из разных источников. Нормализует названия (NaVi / Na\`Vi / Natus Vincere → один ключ). Считает форму команды (WWLWL), H2H статистику |
| `analyzer/analyzer.py` | Принимает запрос → собирает данные через Aggregator → возвращает готовый текстовый отчёт. Никаких прогнозов — только факты |

---

### ✅ Фаза 5 — Telegram-бот

| Файл | Что делает |
|---|---|
| `bot/handlers/start.py` | `/start` — регистрация пользователя, `/help` — список команд |
| `bot/handlers/matches.py` | `/upcoming cs2\|dota2` — предстоящие матчи, `/match Team1 vs Team2` — отчёт по матчу |
| `bot/handlers/teams.py` | `/team Название [игра]` — отчёт по команде, `/patch cs2\|dota2` — последний патч |
| `bot/handlers/admin.py` | `/admin add_channel`, `remove_channel`, `list_channels`, `status` |
| `bot/handlers/__init__.py` | Главный роутер — объединяет все хендлеры |
| `bot/formatters/telegram_format.py` | Экранирование MarkdownV2, разбивка сообщений >4096 символов на части |
| `cache/redis_cache.py` | Redis кэш: отчёты 15 мин, матчи 2 часа. Ключи по MD5 хэшу параметров |

---

### ✅ Фаза 7 — Деплой

| Файл | Что делает |
|---|---|
| `Dockerfile` | Python 3.11 + системные зависимости для Playwright + Chromium |
| `docker-compose.yml` | 3 контейнера: бот + PostgreSQL 16 + Redis 7. Healthcheck, автоперезапуск |
| `main.py` | Точка входа: инициализация БД → Redis → middleware сессий → роутеры → планировщик → polling |
| `README.md` | Инструкция по запуску |
| `.gitignore` | Исключает `.env`, `__pycache__`, сессии Telethon |

---

## Структура файлов (итог)

```
Bot_Stavka/
├── bot/
│   ├── formatters/
│   │   ├── __init__.py
│   │   └── telegram_format.py      ✅
│   ├── handlers/
│   │   ├── __init__.py             ✅
│   │   ├── admin.py                ✅
│   │   ├── matches.py              ✅
│   │   ├── start.py                ✅
│   │   └── teams.py                ✅
│   └── keyboards/
│       └── __init__.py             ✅ (пусто, под будущие кнопки)
├── collectors/
│   ├── __init__.py                 ✅
│   ├── hltv.py                     ✅
│   ├── liquipedia.py               ✅
│   ├── opendota.py                 ✅
│   ├── patches.py                  ✅
│   └── telegram_collector.py       ✅
├── aggregator/
│   ├── __init__.py                 ✅
│   └── aggregator.py               ✅
├── analyzer/
│   ├── __init__.py                 ✅
│   └── analyzer.py                 ✅
├── cache/
│   ├── __init__.py                 ✅
│   └── redis_cache.py              ✅
├── db/
│   ├── __init__.py                 ✅
│   ├── database.py                 ✅
│   └── models.py                   ✅
├── scheduler/
│   ├── __init__.py                 ✅
│   └── scheduler.py                ✅
├── .env.example                    ✅
├── .gitignore                      ✅
├── config.py                       ✅
├── docker-compose.yml              ✅
├── Dockerfile                      ✅
├── main.py                         ✅
├── README.md                       ✅
├── requirements.txt                ✅
└── PROGRESS.md                     ← этот файл
```

---

## Что нужно сделать перед запуском

### Шаг 1 — Создать `.env`

Скопировать `.env.example` → `.env` и заполнить:

```
BOT_TOKEN=        ← получить у @BotFather в Telegram
ADMIN_IDS=        ← твой Telegram ID (узнать у @userinfobot)

TG_API_ID=        ← my.telegram.org → API development tools
TG_API_HASH=      ← там же
TG_PHONE=         ← номер телефона аккаунта Telegram

DB_PASSWORD=      ← придумать пароль для PostgreSQL
```

### Шаг 2 — Запустить

```bash
docker-compose up -d
```

Всё. PostgreSQL и Redis поднимутся автоматически, таблицы создадутся при первом старте.

### Шаг 3 — Добавить Telegram-каналы для мониторинга

В боте написать:
```
/admin add_channel @csgo_analytics
/admin add_channel @dota2_bets
```

---

## Что делать дальше (следующие задачи)

| Приоритет | Задача |
|---|---|
| 🔴 Высокий | Заполнить `.env` и проверить запуск |
| 🔴 Высокий | Протестировать `/upcoming dota2` — первая живая команда |
| 🟡 Средний | Добавить inline-кнопки в отчёты (навигация между разделами) |
| 🟡 Средний | Добавить `/player nickname` — отчёт по игроку |
| 🟡 Средний | Расширить словарь нормализации команд в `aggregator.py` |
| 🟢 Низкий | Alembic миграции вместо `create_all` |
| 🟢 Низкий | Мониторинг через Prometheus / Grafana |
| 🟢 Низкий | Уведомления о начале матчей (push-нотификации) |

---

## Известные ограничения

- **HLTV** — может менять структуру HTML, тогда нужно обновить CSS-селекторы в `collectors/hltv.py`
- **Liquipedia** — rate limit 30 сек между запросами, данные обновляются медленно
- **Telethon** — при первом запуске попросит ввести код из SMS (создаст файл сессии `esports_bot_session.session`)
- **Dota2 патчи** — сайт рендерится через JS, парсер может не найти данные если Valve изменит структуру
