# 戦 Bot Stavka — Esports Analytics & Predictions

> **AI-powered web dashboard** для анализа CS2/Dota2 матчей и управления виртуальными ставками на основе данных HLTV, OpenDota, Liquipedia и аналитики новостей.

![Status](https://img.shields.io/badge/status-production%20beta-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-1.1.0-orange)

## 🎨 Веб-панель (Edo Noir UI)

Главная фишка — **красивая тёмная веб-панель** с полным анализом матчей в реальном времени.

**Что видишь на сайте:**

### 📊 Главная (Dashboard)
- **Hero Card** — "Pick of the Day" (самый уверенный предикт дня)
- **4 статистики** — матчей сегодня, команд в базе, винрейт, ROI
- **Ближайшие матчи** — live и грядущие с предиктами
- **История ставок** — ROI, P&L в реальном времени

### 📅 Сегодня (Today)
- Все предикты на текущий день
- Разбиение по играм (CS2 / Dota2)
- Прогресс-бары уверенности

### ⚔ / ✦ Матчи (CS2 / Dota2)
- Live-матчи с пульсирующим индикатором
- Предстоящие матчи на 72 часа
- Быстрый просмотр вероятностей

### 📈 Результаты
- Таблица завершённых матчей
- Счёты и информация о турнирах
- Кликабельные строки для полного анализа

### 💰 Ставки
- ROI + винрейт + P&L
- Аналитика по уверенности предиктора
- История ставок с фильтрацией по статусу

### 🏆 Команды
- Рейтинги команд
- Форма (W/L/D/U)
- Состав и последние матчи
- Поиск по названию

## 🔍 Быстрый старт

### 1. Клонировать репо
```bash
git clone https://github.com/iSolikin/bot-stavka.git
cd bot-stavka
```

### 2. Настроить .env
```bash
cp .env.example .env
# Заполни:
# - BOT_TOKEN (Telegram, если хочешь бота)
# - DB_PASSWORD (PostgreSQL)
# - TG_API_ID, TG_API_HASH (для парсинга чатов — опционально)
```

### 3. Запустить (Docker)
```bash
docker-compose up -d
```
Веб-панель откроется на: **http://localhost:8000**

### 4. Локально (без Docker)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

pip install -r requirements.txt
python main.py
```

## 🏗 Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                      Веб-панель (8000)                       │
│                    (FastAPI + Edo Noir UI)                  │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼──────────┐  ┌──────▼──────────────┐
│   PostgreSQL     │  │   Redis Cache       │
│   (Matches,      │  │   (Hot data)        │
│    Teams, Bets)  │  │                     │
└──────────────────┘  └─────────────────────┘
        ▲                     ▲
        └─────────┬───────────┘
                  │
        ┌─────────▼────────────┐
        │   Aggregator         │
        │ (Объединение данных) │
        └─────────┬────────────┘
                  │
        ┌─────────▼────────────┐
        │   Analyzer           │
        │ (Формирование        │
        │  предиктов + факты)  │
        └─────────┬────────────┘
                  │
        ┌─────────▼───────────────────────────┐
        │        Collectors                   │
        ├─────────────────────────────────────┤
        │ ◆ HLTV (CS2 матчи, рейтинги)       │
        │ ◆ OpenDota (Dota2 матчи)           │
        │ ◆ Liquipedia (Турниры, форматы)    │
        │ ◆ Steam/Dota2.com (Патчи)          │
        │ ◆ Telegram (Новости, инсайды)      │
        │ ◆ Market (Котировки, букмекеры)    │
        │ ◆ News (Новостные каналы)          │
        └─────────────────────────────────────┘
```

## 📁 Структура проекта

```
bot-stavka/
├── web/                    # 🔥 Веб-панель
│   └── index.html          # Edo Noir UI (Dark theme + Japanese vibes)
│
├── bot/                    # Telegram бот (опционально)
│   ├── handlers/           # Команды /match, /team, /upcoming
│   ├── formatters/         # Форматирование сообщений
│   └── keyboards/          # Клавиатуры + inline-кнопки
│
├── analyzer/               # 🧠 Предикты + анализ
│   ├── predictor.py        # ML модель (логрег на факторах)
│   ├── market_predictor.py # Анализ рыночных котировок
│   ├── news_analyzer.py    # Анализ влияния новостей
│   └── daily_analysis.py   # Дневные отчёты
│
├── collectors/             # 📡 Сборщики данных
│   ├── hltv.py             # CS2: матчи, рейтинги, форма
│   ├── opendota.py         # Dota2: матчи, команды
│   ├── liquipedia.py       # Турниры, форматы, составы
│   ├── patches.py          # Патчи CS2/Dota2
│   ├── telegram_collector.py # Парсинг ТГ-каналов
│   ├── odds.py             # Букмекерские коэффициенты
│   └── rating.py           # Рейтинговые системы
│
├── aggregator/             # 🔗 Объединение + нормализация
│   └── aggregator.py       # Merge данных из разных источников
│
├── bets/                   # 💰 Виртуальный банк
│   └── virtual_bets.py     # ROI, винрейт, P&L, логика ставок
│
├── db/                     # 🗄 База данных
│   ├── models.py           # SQLAlchemy модели
│   └── database.py         # Подключение PostgreSQL
│
├── cache/                  # ⚡ Redis кэш
│   └── redis_cache.py      # Hot data + сессии
│
├── scheduler/              # ⏰ Автоматизация
│   └── scheduler.py        # APScheduler (update каждые 2 часа)
│
├── web_app.py              # 🌐 FastAPI сервер + REST API
├── main.py                 # 🚀 Точка входа
├── config.py               # ⚙ Конфигурация
├── requirements.txt        # Python зависимости
├── docker-compose.yml      # Docker (PostgreSQL + Redis)
├── .env.example            # Шаблон переменных окружения
├── CLAUDE.md               # Гайд для разработчиков
├── CONTRIBUTING.md         # Как контрибьютить
├── PROGRESS.md             # История разработки
└── README.md               # Этот файл
```

## 📊 REST API Эндпоинты

Все данные доступны через REST API (используется веб-панелью):

### Статистика
```
GET /api/stats/summary          — Сводная статистика
```

### Матчи
```
GET /api/matches/upcoming       — Предстоящие матчи (query: ?game=cs2, ?hours=48)
GET /api/matches/results        — Завершённые матчи (query: ?game=dota2, ?limit=40)
GET /api/today                  — Предикты на сегодня
GET /api/predict                — Предикт на конкретный матч
                                  (query: ?team1=X, ?team2=Y, ?game=cs2, ?match_id=123)
```

### Ставки
```
GET /api/bets/stats             — Статистика (ROI, винрейт, P&L)
GET /api/bets/list              — История ставок (query: ?limit=50, ?status=won)
```

### Команды
```
GET /api/teams                  — Список команд (query: ?game=cs2, ?limit=50, ?search=NaVi)
GET /api/team/{name}            — Детали команды (query: ?game=dota2)
```

## 🤖 Telegram бот (опционально)

Если хочешь — есть и Telegram бот с командами:

| Команда | Описание |
|---|---|
| `/today` | Предикты на сегодня |
| `/upcoming cs2` | Матчи CS2 на 48 часов |
| `/match Team1 vs Team2` | Анализ матча |
| `/team TeamName` | Отчёт по команде |
| `/bets` | История ставок |
| `/stats` | Статистика ROI |

Но основное — **это веб-панель** 🌐

## 🔄 Git Workflow

### Создание новой фичи
```bash
git checkout -b feature/название-фичи
# Делаешь изменения
git add .
git commit -m "Add: описание"
git push origin feature/название-фичи
# Создаёшь Pull Request на GitHub
```

### Синхронизация между участниками
```bash
git pull origin main
# Получишь свежие изменения от других
```

## 🛠 Разработка

### Как добавить новый источник данных?
1. Создай `collectors/my_source.py`
2. Реализуй `BaseCollector` интерфейс
3. Добавь в `aggregator.py`
4. Коммит: `Add collector: My Source`

### Как улучшить предиктор?
1. Edit `analyzer/predictor.py`
2. Добавь новый фактор/фичу
3. Протестируй на истории
4. Коммит: `Improve: predictor with X feature`

## 📦 Зависимости

- **Python 3.11+**
- **PostgreSQL** (или SQLite локально)
- **Redis** (кэш)
- **FastAPI** (веб)
- **SQLAlchemy** (ORM)
- **aiogram** (Telegram бот)
- **APScheduler** (автоматизация)
- **Playwright** (веб-скрейпинг)

## 🐳 Docker

```bash
# Запустить всё (PostgreSQL + Redis + приложение)
docker-compose up -d

# Логи
docker-compose logs -f

# Остановить
docker-compose down
```

## 📚 Документация

- **CLAUDE.md** — детальный гайд для разработчиков
- **CONTRIBUTING.md** — как контрибьютить в проект
- **PROGRESS.md** — история разработки и фазы проекта
- **Issues** — текущие задачи и баги
- **Pull Requests** — обсуждение изменений

## 👥 Командная разработка

- **Owner:** [@iSolikin](https://github.com/iSolikin)
- **Collaborators:** [@szakat200](https://github.com/szakat200)

Приглашаем больше контрибьюторов! 🚀

## 📝 Лицензия

MIT License — используй свободно в своих проектах.

---

**Версия:** 1.1.0  
**UI Theme:** Edo Noir (Dark + Japanese aesthetics)  
**Status:** Production Beta  
**Last Updated:** May 2026

**Вопросы?** Создавай Issues или Pull Requests! 💬
