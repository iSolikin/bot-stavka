# 🤝 Contributing to Bot Stavka

Спасибо за интерес к проекту! Вот как можно помочь разработке.

## 🚀 Как начать?

### 1. Fork репо
```bash
# На GitHub нажми кнопку "Fork"
```

### 2. Клонируй свой fork
```bash
git clone https://github.com/ТВО-ИМЯABC/bot-stavka.git
cd bot-stavka
```

### 3. Добавь upstream
```bash
git remote add upstream https://github.com/iSolikin/bot-stavka.git
```

## 📋 Git Workflow

### Перед началом работы
```bash
# Обнови main
git fetch upstream
git checkout main
git merge upstream/main
```

### Создание фичи
```bash
# Из ветки main
git checkout -b feature/твоя-фича

# Например:
# - feature/add-market-predictor
# - feature/improve-web-ui
# - feature/fix-team-normalization
```

### Делаешь изменения
```bash
git add .
git commit -m "Add: описание что добавил"
```

**Правила коммитов:**
```
Add:        Новая фичировка / компонент / функция
Improve:    Улучшение существующего функционала
Fix:        Баг-фикс
Refactor:   Переписывание кода без изменения поведения
Docs:       Обновление документации
Test:       Добавление тестов
Perf:       Оптимизация производительности
```

Пример:
```
Add: market price analysis in predictor
Fix: team name normalization for dota2
Improve: web UI responsiveness on mobile
Docs: update API endpoints documentation
```

### Отправляешь ветку
```bash
git push origin feature/твоя-фича
```

### Создаёшь Pull Request
1. Иди на GitHub
2. Нажми "Compare & pull request"
3. Заполни описание по шаблону
4. Жди review

## 📂 Структура кода

### Веб-панель
```
web/
├── index.html          # Edo Noir UI (single file app)
│                       # Используй существующий стиль
│                       # Цвета: shu (red), ai (cyan), sakura (pink)
```

### Анализаторы
```
analyzer/
├── predictor.py        # ML модель (логистическая регрессия)
├── market_predictor.py # Анализ рынка
├── news_analyzer.py    # Обработка новостей
└── daily_analysis.py   # Дневные отчёты
```

**Требование:** каждый новый анализатор должен быть интегрирован в `analyzer.py` и доступен через REST API.

### Collectors
```
collectors/
├── hltv.py             # CS2
├── opendota.py         # Dota2
├── liquipedia.py       # Турниры
├── telegram_collector.py # ТГ каналы
├── news_processor.py    # Новости
└── ...
```

**Требование:** новый collector должен наследовать `BaseCollector` и быть зарегистрирован в `aggregator.py`.

### REST API
```
web_app.py
├── GET /api/stats/summary
├── GET /api/matches/upcoming
├── GET /api/predict
├── GET /api/bets/stats
└── ...
```

**Требование:** новые endpoints должны быть задокументированы в README.

## 🧪 Тестирование

### Локальный запуск
```bash
# Без Docker
python main.py

# С Docker
docker-compose up -d
```

Веб-панель: http://localhost:8000

### Проверка
- [ ] Веб-панель загружается без ошибок
- [ ] API эндпоинты доступны
- [ ] Данные обновляются корректно
- [ ] Нет конфликтов слияния с main

### Логи
```bash
docker-compose logs -f

# Или
tail -f bot_out.txt
```

## 📝 Коммит-сообщения

**Хорошо:**
```
Add: market sentiment analysis in predictor

Added new features:
- Price momentum calculation
- Volume analysis
- Historical volatility

Related to #42
```

**Плохо:**
```
fix stuff
updated code
changes
```

## 🔍 Code Review

### Что проверяют при review?
1. ✅ Код следует стилю проекта
2. ✅ Логика корректна и эффективна
3. ✅ Нет дублирования кода
4. ✅ Комментарии понятны
5. ✅ Тесты написаны (если нужны)
6. ✅ Документация обновлена

### Как ответить на feedback?
```bash
# Делаешь правки
git add .
git commit -m "Review feedback: описание изменения"
git push origin feature/твоя-фича

# GitHub автоматически обновит PR
```

**Не делай force push** во время review!

## 🎨 Стиль кода

### Python
```python
# PEP 8
def analyze_match(team1: str, team2: str) -> dict:
    """Анализирует матч и возвращает предикт."""
    
    # Комментарии для сложной логики
    probability = calculate_probability(team1, team2)
    
    return {
        "winner": team1 if probability > 0.5 else team2,
        "confidence": "high" if abs(probability - 0.5) > 0.2 else "low"
    }
```

### JavaScript / HTML
```javascript
// Используй существующий стиль из index.html
// Переменные: var(--shu), var(--ai), var(--sakura)
// Функции: async/await, try/catch

async function fetchMatches() {
  try {
    const response = await fetch('/api/matches/upcoming');
    return response.json();
  } catch (e) {
    console.error('Failed to fetch matches', e);
  }
}
```

## 📚 Документация

### Обновляй документацию если:
- [ ] Добавляешь новый API endpoint
- [ ] Меняешь имя функции
- [ ] Добавляешь новый collector
- [ ] Меняешь структуру данных

### Где документировать?
- `README.md` — новые эндпоинты
- Комментарии в коде — сложная логика
- `CLAUDE.md` — процесс разработки
- `PROGRESS.md` — историю изменений

## 🚫 Что НЕ делать

- ❌ Не коммитить `.env` файлы
- ❌ Не коммитить `__pycache__/`, `node_modules/`, `.DS_Store`
- ❌ Не менять глобальные константы
- ❌ Не использовать print() вместо логирования
- ❌ Не делать force push на main
- ❌ Не сливать PR без review

## 🤔 Вопросы?

- **Issues** — для багов и фич-реквестов
- **Discussions** — для вопросов и идей
- **Email** — [@iSolikin](https://github.com/iSolikin)

## 📊 Что приветствуется?

- 🎯 Фичи на веб-панели (UI улучшения)
- 🔍 Новые collectors и источники данных
- 🧠 Улучшения в анализаторах
- 🧪 Тесты и CI/CD improvements
- 📚 Документация и примеры
- 🐛 Баг-фиксы

## 🏆 Спасибо!

Каждый контрибьюшн ценен! Спасибо за помощь в развитии проекта 🚀

---

**Happy coding!** 💻
