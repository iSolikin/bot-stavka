# Esports Bot — аналитика ставок CS2 / Dota2

Telegram-бот для сбора и анализа статистики по CS2 и Dota2.
Только факты и цифры — никаких прогнозов.

## Быстрый старт

### 1. Настройка окружения

```bash
cp .env.example .env
# Заполни .env своими данными
```

### 2. Запуск через Docker (рекомендуется)

```bash
docker-compose up -d
```

### 3. Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Регистрация |
| `/upcoming cs2` | Матчи CS2 на 48 часов |
| `/upcoming dota2` | Матчи Dota2 на 48 часов |
| `/match NaVi vs Vitality` | Отчёт по матчу |
| `/team NaVi` | Отчёт по команде CS2 |
| `/team OG dota2` | Отчёт по команде Dota2 |
| `/patch cs2` | Последний патч CS2 |
| `/patch dota2` | Последний патч Dota2 |
| `/help` | Все команды |

## Команды администратора

| Команда | Описание |
|---|---|
| `/admin add_channel @channel` | Добавить Telegram-канал |
| `/admin remove_channel @channel` | Убрать канал |
| `/admin list_channels` | Список каналов |
| `/admin status` | Состояние системы |

## Источники данных

- **OpenDota API** — Dota2: матчи, команды, игроки
- **HLTV** — CS2: рейтинги, матчи (Playwright)
- **Liquipedia** — турниры, составы
- **Steam / Dota2.com** — патч-ноуты
- **Telegram-каналы** — инсайды (Telethon)

## Структура проекта

```
├── bot/            # Telegram-бот (handlers, keyboards, formatters)
├── collectors/     # Сборщики данных
├── aggregator/     # Объединение данных из разных источников
├── analyzer/       # Формирование текстовых отчётов
├── db/             # SQLAlchemy модели и подключение
├── cache/          # Redis кэш
├── scheduler/      # APScheduler планировщик
├── config.py       # Конфигурация
└── main.py         # Точка входа
```
