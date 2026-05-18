# Changelog

Все значительные изменения в этом проекте будут задокументированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
и этот проект придерживается [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-05-18

### 🎨 Added
- **Edo Noir Web Dashboard** — красивая тёмная панель с японской тематикой
  - Hero card "Pick of the Day"
  - 7 страниц анализа (Dashboard, Today, CS2, Dota2, Results, Bets, Teams)
  - Responsive design
  - Real-time updates

- **Market Price Predictor** (`analyzer/market_predictor.py`)
  - Анализ котировок букмекеров
  - Расчёт value bets
  - Сравнение с собственными предиктами

- **News Analyzer** (`analyzer/news_analyzer.py`)
  - Парсинг новостных каналов
  - Анализ влияния новостей на матчи
  - Интеграция в предикты

- **News Processor** (`analyzer/news_processor.py`)
  - Обработка потока новостей
  - Классификация важности
  - Архивирование

- **GitHub Actions CI/CD**
  - Автоматические тесты при каждом push
  - Проверка кода (flake8, black, isort)
  - Security scanning (bandit, safety)
  - Docker build validation

- **Contributing Guidelines**
  - CONTRIBUTING.md — подробный гайд для разработчиков
  - Issue templates (bug, feature)
  - PR template
  - CODE_OF_CONDUCT.md

### 📈 Improved
- Collectors (OpenDota, Telegram) — расширенная функциональность
- Scheduler — более гибкое расписание обновлений
- Web API — новые endpoints и фильтры
- Database models — дополнительные поля для анализа
- Performance — оптимизация запросов к БД

### 🐛 Fixed
- Team name normalization для Dota2
- H2H матчей — исправлена сортировка
- Redis кэш — проблемы с истечением

### 🔄 Changed
- README переписан с акцентом на веб-панель
- Структура проекта переорганизована
- Документация обновлена

### 📚 Docs
- Полная переписка README.md
- CLAUDE.md — детальный dev guide
- PROGRESS.md — история разработки
- API documentation в README

---

## [1.0.0] — 2026-05-17

### 🎯 Initial Release

#### 🎨 Added
- **Telegram Bot** с командами анализа матчей
- **Web API** (FastAPI) с REST endpoints
- **PostgreSQL Database** для хранения данных
- **Redis Cache** для оптимизации

#### 📡 Collectors
- HLTV (CS2 матчи, рейтинги)
- OpenDota (Dota2 матчи, команды)
- Liquipedia (Турниры, форматы)
- Steam/Dota2.com (Патчи)
- Telegram (Новости, инсайды)

#### 🧠 Analyzers
- Predictor (логистическая регрессия)
- Daily analysis (дневные отчёты)
- Virtual bets (ROI, винрейт)

#### 🔧 Infrastructure
- Docker Compose для легкого развёртывания
- APScheduler для автоматизации
- SQLAlchemy ORM для работы с БД

---

## Версионирование

Версии имеют формат `MAJOR.MINOR.PATCH`:

- **MAJOR** — полностью несовместимые изменения API
- **MINOR** — обратно совместимые новые фичи
- **PATCH** — обратно совместимые баг-фиксы

---

## Как читать этот файл?

- **Added** — новая функциональность
- **Changed** — изменения в существующей функциональности
- **Deprecated** — функциональность которая вскоре будет удалена
- **Removed** — удалённая функциональность
- **Fixed** — исправленные баги
- **Security** — уязвимости безопасности
- **Improved** / **Optimized** — улучшения производительности

---

## Планы на будущее

### v1.2.0
- [ ] WebSocket для real-time обновлений
- [ ] Telegram bot улучшения
- [ ] Mobile-friendly веб-панель
- [ ] Экспорт данных (CSV, JSON)

### v2.0.0
- [ ] Machine Learning модель (Neural Network)
- [ ] Мультиязычная поддержка
- [ ] Пользовательские аккаунты и настройки
- [ ] API V2 с более мощными фильтрами

---

[1.1.0]: https://github.com/iSolikin/bot-stavka/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/iSolikin/bot-stavka/releases/tag/v1.0.0
