# Bot Stavka — Esports Analytics AI Assistant

Совместный проект для разработки CS2/Dota2 аналитики и виртуальных ставок.

## 🚀 Быстрый старт

### Клонировать репо

```bash
# Если у тебя есть доступ
git clone https://github.com/iSolikin/bot-stavka.git
cd bot-stavka
```

### Запустить бота

```bash
# 1. Создай .env из шаблона (скопируй .env.example → .env)
# 2. Заполни переменные:
#    - BOT_TOKEN (Telegram Bot API token)
#    - ADMIN_IDS (твой Telegram ID)
#    - TG_API_ID, TG_API_HASH, TG_PHONE (для Telethon)
#    - DB_PASSWORD (PostgreSQL пароль)

# 3. Запустить через Docker
docker-compose up -d

# Или напрямую (нужен Python 3.11+, PostgreSQL, Redis)
pip install -r requirements.txt
python main.py
```

### Запустить веб-панель

Веб-панель уже включена в docker-compose. Открой:
```
http://localhost:8000
```

**Новый дизайн:** Edo Noir (тёмная японская тема) с иероглифами 戦, боками, анализом матчей.

## 📁 Структура

```
.
├── bot/                    # Telegram бот
│   ├── handlers/           # Обработчики команд
│   ├── formatters/         # Форматирование сообщений
│   └── keyboards/          # Клавиатуры + inline-кнопки
├── collectors/             # Сборщики данных
│   ├── hltv.py            # CS2 матчи, рейтинги
│   ├── opendota.py        # Dota2 матчи
│   ├── liquipedia.py      # Турниры, форматы
│   └── telegram_collector.py  # Парсинг каналов
├── analyzer/              # Анализ + предикты
│   ├── predictor.py       # ML модель (логистическая регрессия)
│   └── daily_analysis.py  # Дневные отчёты
├── bets/                  # Виртуальный банк
│   └── virtual_bets.py    # ROI, винрейт, P&L
├── db/                    # База данных (PostgreSQL)
│   ├── models.py          # SQLAlchemy модели
│   └── database.py        # Подключение
├── cache/                 # Redis кэш
├── scheduler/             # APScheduler
├── web/                   # Веб-панель (FastAPI)
│   └── index.html         # Новый UI (Edo Noir)
├── web_app.py             # FastAPI endpoints
└── main.py                # Точка входа (бот + веб)
```

## 🔗 Git workflow

### Ежедневная работа

```bash
# Создать ветку для фичи
git checkout -b feature/название

# После изменений
git add .
git commit -m "Описание того что изменил"
git push origin feature/название

# Когда готово — создаёшь Pull Request на GitHub
```

### Синхронизация между ПК/телефоном

```bash
# Перед началом работы
git pull origin main

# После фиксов
git push origin main
```

## 💻 Claude Code интеграция

### С этого ПК

```bash
# Инициализировать Claude Code в проекте
# (если еще не сделано)
```

### Промпты через Claude

Можешь давать Claude промпты вроде:
- "Добавь новый обработчик /player_stats"
- "Оптимизируй collector/hltv.py"
- "Исправь баг в виртуальных ставках"
- "Улучши дизайн страницы Результаты"

Claude автоматически:
1. Найдёт нужные файлы
2. Сделает изменения
3. Скомитит в git
4. Запушит на GitHub

## 🔐 Секретные данные

**Важно:** .env файл защищён .gitignore и никогда не попадёт в git.

Переменные окружения (заполни в .env):
```env
# Telegram
BOT_TOKEN=ххх
ADMIN_IDS=123456789,987654321

# Telethon (для парсинга чатов)
TG_API_ID=xxxxx
TG_API_HASH=xxxxxxx
TG_PHONE=+7xxxxxxxx

# База данных
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=xxxxx

# Redis
REDIS_URL=redis://localhost:6379

# Бизнес
INITIAL_BANK=10000
```

## 📊 API эндпоинты

Веб-панель использует REST API (FastAPI):

```
GET  /api/stats/summary           — Статистика системы
GET  /api/matches/upcoming        — Предстоящие матчи
GET  /api/matches/results         — Завершённые матчи
GET  /api/predict                 — Предикт на матч
GET  /api/today                   — Предикты на сегодня
GET  /api/bets/stats              — Статистика ставок
GET  /api/bets/list               — История ставок
GET  /api/teams                   — Список команд
GET  /api/team/{name}             — Детали команды
```

## 🎨 Веб-дизайн (Edo Noir)

Новый дизайн — тёмная японская тема:

**Цвета:**
- 朱 (shu) — vermillion red (#e63946) — основной accent
- 藍 (ai) — indigo cyan (#4cc9f0) — secondary
- 桜 (sakura) — pink (#f72585) — accents
- 金 (kin) — gold (#f4c430) — highlights

**Секции:**
- **Главная** — hero-карточка "Pick of the Day" + статы + матчи + ставки
- **Сегодня** — предикты по играм с прогресс-барами
- **CS2/Dota2** — матчи live и предстоящие
- **Результаты** — таблица завершённых
- **Ставки** — ROI + таблица + аналитика по уверенности
- **Команды** — сетка карточек с рейтингом и поиском

Каждый раздел имеет иероглиф (本 日 試 結 賭 隊).

## 🤖 Как работает аналитика

### 1. Сбор данных (Collectors)

```
HLTV → CS2 матчи, рейтинги команд
OpenDota → Dota2 матчи, патчи
Liquipedia → Турниры, форматы
Telegram-каналы → Новости, tips
```

### 2. Агрегация (Aggregator)

Объединяет данные из разных источников, нормализует названия команд.

### 3. Анализ (Analyzer)

```python
# Для каждого матча вычисляет:
- Форму команд (последние 5 игр)
- Историю встреч (H2H)
- Стиль игры
- Важность матча (турнир, рейтинг)
```

### 4. Прогноз (Predictor)

```python
# Логистическая регрессия:
model.predict(features) → вероятность победы team1
```

### 5. Ставки (Virtual Bets)

```python
# Виртуальный банк 10k условных единиц
# Для каждого матча:
bet_amount = confidence * odds * base_bet
roi = (profit / total_bet) * 100
```

### 6. Отчёты (Scheduler)

APScheduler запускает анализ каждые 2 часа + дневные отчёты в 8:00 UTC.

## 📝 Коммит-стиль

```bash
# Фичи
git commit -m "Add /player_stats handler with form streak analytics"

# Баги
git commit -m "Fix team name normalization in H2H calculation"

# Улучшения
git commit -m "Optimize database queries in aggregator"

# Документация
git commit -m "Update README with API endpoints and setup guide"
```

## 🐛 Если что-то сломалось

1. Проверь логи: `docker-compose logs -f`
2. Убедись что .env заполнен
3. Проверь подключение к PostgreSQL/Redis
4. Перезагрузи контейнеры: `docker-compose restart`

## 📞 Контакты

- **Мой GitHub:** https://github.com/iSolikin
- **Репо:** https://github.com/iSolikin/bot-stavka
- **Telegram:** @iSolikin

---

**Версия:** 1.0 (Edo Noir UI + полная аналитика)  
**Последнее обновление:** май 2026  
**Статус:** Production-ready (бета)
