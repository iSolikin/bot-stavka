# 🏗 System Architecture

Полная архитектура Bot Stavka — от сбора данных до веб-панели.

## 📊 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   🌐 ВЕБ-ПАНЕЛЬ (MAIN UI)                       │
│                  http://localhost:8000                          │
│         (Edo Noir Dark UI + Real-time Analytics)                │
│                                                                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │ Dashboard  │ │   Today    │ │  Results   │ │   Bets     │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                  │
│  │   CS2      │ │   Dota2    │ │   Teams    │                  │
│  └────────────┘ └────────────┘ └────────────┘                  │
│                                                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │ REST API
        ┌──────────────┴──────────────┐
        │                             │
    ┌───▼──────────┐      ┌──────────▼────┐
    │   FastAPI    │      │ WebSocket /   │
    │   Server     │      │ Server-Sent   │
    │   (8000)     │      │ Events        │
    └───┬──────────┘      └──────────┬────┘
        │                            │
        └────────────┬───────────────┘
                     │
        ┌────────────▼──────────────┐
        │   APPLICATION LAYER       │
        │   (web_app.py + routes)   │
        └────────────┬──────────────┘
                     │
        ┌────────────▼──────────────────────┐
        │   BUSINESS LOGIC LAYER             │
        ├────────────────────────────────────┤
        │                                    │
        │  ┌──────────────────────────────┐ │
        │  │ ANALYZERS                    │ │
        │  ├──────────────────────────────┤ │
        │  │ • predictor.py               │ │
        │  │   (logistic regression)      │ │
        │  │ • market_predictor.py        │ │
        │  │   (price analysis)           │ │
        │  │ • news_analyzer.py           │ │
        │  │   (sentiment + impact)       │ │
        │  │ • daily_analysis.py          │ │
        │  │   (reports)                  │ │
        │  └──────────────────────────────┘ │
        │                                    │
        │  ┌──────────────────────────────┐ │
        │  │ AGGREGATOR                   │ │
        │  │ (data normalization)         │ │
        │  └──────────────────────────────┘ │
        │                                    │
        │  ┌──────────────────────────────┐ │
        │  │ VIRTUAL BETS                 │ │
        │  │ (ROI, Win Rate, P&L)         │ │
        │  └──────────────────────────────┘ │
        │                                    │
        └────────────┬─────────────────────┘
                     │
        ┌────────────▼──────────────────────┐
        │   DATA LAYER                       │
        ├────────────────────────────────────┤
        │                                    │
        │  ┌──────────────────────────────┐ │
        │  │ COLLECTORS (Real-time updates)│
        │  ├──────────────────────────────┤ │
        │  │ • HLTV.py                   │ │
        │  │   (CS2: matches, ratings)   │ │
        │  │ • OpenDota.py               │ │
        │  │   (Dota2: matches, stats)   │ │
        │  │ • Liquipedia.py             │ │
        │  │   (Tournaments, formats)    │ │
        │  │ • Patches.py                │ │
        │  │   (Game updates)            │ │
        │  │ • Telegram_collector.py     │ │
        │  │   (News & insights)         │ │
        │  │ • News_processor.py         │ │
        │  │   (News aggregation)        │ │
        │  │ • Market.py                 │ │
        │  │   (Bookmaker odds)          │ │
        │  └──────────────────────────────┘ │
        │                                    │
        └────────────┬─────────────────────┘
                     │
        ┌────────────▼──────────────────────┐
        │   EXTERNAL DATA SOURCES            │
        ├────────────────────────────────────┤
        │ • HLTV.org                         │
        │ • OpenDota.com API                 │
        │ • Liquipedia.com                   │
        │ • Steam/Dota2.com                  │
        │ • Telegram channels                │
        │ • News websites                    │
        │ • Bookmaker APIs                   │
        └────────────────────────────────────┘
```

## 🗄 Database Layer

```
┌──────────────────────────────────────────┐
│        PostgreSQL (Main DB)              │
│          :5432                           │
├──────────────────────────────────────────┤
│                                          │
│  ┌──────────────────────────────────┐   │
│  │ Tables (SQLAlchemy Models)       │   │
│  ├──────────────────────────────────┤   │
│  │ • matches                        │   │
│  │   (id, team1, team2, status...)  │   │
│  │ • predictions                    │   │
│  │   (match_id, team1_prob, conf..) │   │
│  │ • teams                          │   │
│  │   (name, rating, wins/losses..)  │   │
│  │ • players                        │   │
│  │   (name, team, stats)            │   │
│  │ • bets                           │   │
│  │   (match_id, bet_team, odds...)  │   │
│  │ • results                        │   │
│  │   (match_id, score_team1/2...)   │   │
│  │ • tournaments                    │   │
│  │   (name, game, prize_pool)       │   │
│  │ • news                           │   │
│  │   (title, content, sentiment)    │   │
│  └──────────────────────────────────┘   │
│                                          │
└──────────────────────────────────────────┘
          ▲                      ▲
          │                      │
      ┌───┘            ┌─────────┘
      │                │
      │        ┌───────▼────────────────┐
      │        │   Redis Cache          │
      │        │     :6379              │
      │        ├────────────────────────┤
      │        │ • Hot matches (LIVE)   │
      │        │ • Player stats         │
      │        │ • Team ratings         │
      │        │ • Prediction cache     │
      │        │ • Session tokens       │
      │        │ • Rate limits          │
      │        └────────────────────────┘
      │
   ┌──▼──────────────────────┐
   │  SQLAlchemy ORM Layer    │
   │  (db/models.py,          │
   │   db/database.py)        │
   └──────────────────────────┘
```

## ⏰ Scheduler & Updates

```
┌────────────────────────────────────────────────┐
│         APScheduler (Continuous Updates)       │
├────────────────────────────────────────────────┤
│                                                │
│  Every 2 hours:                                │
│  ┌──────────────────────────────────────────┐ │
│  │ 1. Fetch latest matches from collectors  │ │
│  │ 2. Update team ratings and stats         │ │
│  │ 3. Recalculate predictions               │ │
│  │ 4. Update virtual bets status            │ │
│  │ 5. Generate daily reports                │ │
│  │ 6. Cache hot data in Redis               │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  Daily (8:00 UTC):                             │
│  ┌──────────────────────────────────────────┐ │
│  │ 1. Generate daily analysis report        │ │
│  │ 2. Calculate ROI/Winrate for bets        │ │
│  │ 3. Send reports (Bot/Email)              │ │
│  └──────────────────────────────────────────┘ │
│                                                │
└────────────────────────────────────────────────┘
```

## 🔄 Data Flow Example: Match Prediction

```
1. COLLECTION
   HLTV.org → [hltv_collector] → PostgreSQL
                                      ↓
2. AGGREGATION
   PostgreSQL → [aggregator] → Normalized teams & stats → PostgreSQL

3. ANALYSIS
   PostgreSQL → [predictor]
                    ↓
   Load features:
   • Team ratings
   • Form (last 5 games)
   • H2H history
   • Recent opponents
   • Map pool (CS2)
   • Hero pool (Dota2)
                    ↓
   Apply ML model (logistic regression)
                    ↓
   Output: team1_prob, team2_prob, confidence
                    ↓
   PostgreSQL (predictions table)

4. API & WEB DISPLAY
   PostgreSQL → [web_app.py] → REST API → Web Dashboard
                                           ↓
                                    Real-time update
                                    (WebSocket/SSE)
```

## 🚀 Deployment Architecture

```
┌─────────────────────────────────────────┐
│         Docker Compose                  │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌──────────────┐   │
│  │ App Service  │  │ PostgreSQL   │   │
│  │ :8000        │  │ :5432        │   │
│  │              │  │              │   │
│  │ • FastAPI    │  │ • Main DB    │   │
│  │ • Bot        │  │ • Data       │   │
│  │ • Scheduler  │  │ • Cache      │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
│  ┌──────────────┐  ┌──────────────┐   │
│  │ Redis        │  │ Network      │   │
│  │ :6379        │  │              │   │
│  │              │  │ • bridge     │   │
│  │ • Cache      │  │ • 8000→web  │   │
│  │ • Sessions   │  │ • 5432→db   │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

## 🔐 Security Layers

```
┌────────────────────────────────────────┐
│     Input Validation                   │
│     (FastAPI automatic)                │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│     Rate Limiting                      │
│     (Redis-based)                      │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│     CORS & CSRF Protection             │
│     (FastAPI middleware)               │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│     SQL Injection Prevention           │
│     (SQLAlchemy ORM)                   │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│     Secure Data Storage                │
│     (.env, secrets not in git)         │
└────────────────────────────────────────┘
```

## 📈 Performance Optimization

### Caching Strategy
```
GET /api/predict?team1=X&team2=Y
         ↓
Cache key: f"predict:{team1}:{team2}"
         ↓
Found in Redis? → Yes → Return cached (TTL: 1 hour)
         ↓ No
Compute prediction
         ↓
Store in Redis
         ↓
Return to client
```

### Database Indexes
```
CREATE INDEX idx_matches_status ON matches(status)
CREATE INDEX idx_matches_scheduled ON matches(scheduled_at)
CREATE INDEX idx_predictions_match ON predictions(match_id)
CREATE INDEX idx_teams_game ON teams(game)
CREATE INDEX idx_bets_status ON bets(status)
```

### Query Optimization
- ✅ Use SELECT specific columns (not *)
- ✅ JOIN only needed tables
- ✅ Cache frequently accessed data
- ✅ Batch updates when possible
- ✅ Use pagination for large result sets

---

## 🔗 API Endpoints Mapping

```
Web Dashboard
    ↓
GET /api/stats/summary ← Aggregated statistics
GET /api/matches/upcoming ← Live & upcoming
GET /api/matches/results ← Finished
GET /api/today ← Today's predictions
GET /api/predict?team1=X&team2=Y ← Match analysis
GET /api/bets/stats ← ROI, winrate, P&L
GET /api/bets/list ← Bet history
GET /api/teams ← Team list & search
GET /api/team/{name} ← Team details
```

## 🛠 Development Workflow

```
1. Create feature branch
   git checkout -b feature/new-feature

2. Make changes & commit
   git commit -m "Add: feature description"

3. Push & create PR
   git push origin feature/new-feature

4. GitHub Actions run:
   ✓ Tests (pytest)
   ✓ Lint (flake8, black)
   ✓ Security (bandit)
   ✓ Docker build check

5. Code review & merge
   git checkout main
   git merge feature/new-feature

6. Auto-deploy on tag
   git tag v1.1.0
   git push --tags
   → Release workflow triggers
```

---

**Last Updated:** May 2026  
**Architecture Version:** 1.1.0
