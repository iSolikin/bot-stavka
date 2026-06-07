"""
Веб-сервер для esports-сайта.
Запуск: uvicorn web_app:app --host 0.0.0.0 --port 8000 --reload
Читает ту же bot.db что и бот, работает параллельно с ним.
"""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# --- Пути ---
BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# --- Загружаем .env ---
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

# --- Конфиг ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
# Для SQLite делаем путь абсолютным (важно для Windows и uvicorn --reload)
if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    if not DATABASE_URL:
        DATABASE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / 'bot.db').as_posix()}"
    elif "///" in DATABASE_URL:
        rel = DATABASE_URL.split("///", 1)[1].lstrip("./\\")
        abs_path = (BASE_DIR / rel).resolve().as_posix()
        prefix = DATABASE_URL.split("///")[0]
        DATABASE_URL = f"{prefix}///{abs_path}"

logger = logging.getLogger(__name__)

# --- Движок БД ---
_is_sqlite = DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
else:
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- FastAPI ---
app = FastAPI(title="Esports Analytics", version="1.0.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------- Helpers --------

def _match_dict(m) -> dict:
    return {
        "id": m.id,
        "game": m.game,
        "team1": m.team1_name,
        "team2": m.team2_name,
        "tournament": m.tournament,
        "match_format": m.match_format,
        "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "status": m.status,
        "score_team1": m.score_team1,
        "score_team2": m.score_team2,
        "match_url": m.match_url,
        "source": m.source,
        "tier": m.tier if m.tier is not None else 3,
    }


def _team_dict(t) -> dict:
    total = (t.wins or 0) + (t.losses or 0)
    wr = round(t.wins / total * 100, 1) if total else 0
    return {
        "id": t.id,
        "name": t.name,
        "game": t.game,
        "rating": t.rating,
        "hltv_rating": getattr(t, 'hltv_rating', None),
        "valve_rating": getattr(t, 'valve_rating', None),
        "wins": t.wins or 0,
        "losses": t.losses or 0,
        "winrate": wr,
        "win_rate_last_10": getattr(t, 'win_rate_last_10', None),
        "best_map": getattr(t, 'best_map', None),
        "worst_map": getattr(t, 'worst_map', None),
        "recent_form": getattr(t, 'recent_form', None),
        "rating_history": (lambda h: h[-10:] if h else None)(getattr(t, 'rating_history', None)),
        "map_stats": getattr(t, 'map_stats', None),
        "source": t.source,
        "tag": t.tag,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "last_stats_update": getattr(t, 'last_stats_update', None),
    }


def _bet_dict(b) -> dict:
    return {
        "id": b.id,
        "team1": b.team1_name,
        "team2": b.team2_name,
        "game": b.game,
        "tournament": b.tournament,
        "bet_on": b.bet_on,
        "bet_team": b.bet_team_name,
        "pred_prob": b.pred_prob,
        "confidence": b.confidence,
        "odds": b.odds,
        "stake": b.stake,
        "edge": getattr(b, "edge", None),
        "status": b.status,
        "profit": b.profit,
        "actual_score": b.actual_score,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "settled_at": b.settled_at.isoformat() if b.settled_at else None,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
    }


# -------- Static --------

@app.get("/", include_in_schema=False)
@app.get("/web", include_in_schema=False)
async def serve_index():
    path = WEB_DIR / "index.html"
    if path.exists():
        return FileResponse(str(path))
    return JSONResponse({"status": "ok", "api": "/api/docs"})


# -------- Матчи --------

@app.get("/api/matches/upcoming")
async def matches_upcoming(
    game: Optional[str] = None,
    hours: int = Query(168, ge=1, le=2160),
):
    """Предстоящие и live матчи."""
    from db.models import Match
    async with SessionLocal() as db:
        now = datetime.utcnow()
        filters = [
            Match.status.in_(["upcoming", "live"]),
            Match.scheduled_at >= now - timedelta(hours=3),
            Match.scheduled_at <= now + timedelta(hours=hours),
            Match.team1_name != "TBD",
            Match.team2_name != "TBD",
        ]
        if game:
            filters.append(Match.game == game)
        result = await db.execute(
            select(Match).where(and_(*filters)).order_by(Match.tier, Match.scheduled_at).limit(200)
        )
        return [_match_dict(m) for m in result.scalars().all()]


@app.get("/api/matches/results")
async def matches_results(
    game: Optional[str] = None,
    limit: int = Query(40, ge=1, le=100),
):
    """Завершённые матчи (только с реальными счётами)."""
    from db.models import Match
    from sqlalchemy import or_, and_
    async with SessionLocal() as db:
        q = select(Match).where(
            Match.status == "finished",
            # Показываем только матчи где хотя бы одна команда набрала очки
            or_(
                Match.score_team1 > 0,
                Match.score_team2 > 0,
            ),
        )
        if game:
            q = q.where(Match.game == game)
        q = q.order_by(desc(Match.scheduled_at)).limit(limit)
        result = await db.execute(q)
        return [_match_dict(m) for m in result.scalars().all()]


@app.get("/api/matches/{match_id}")
async def match_detail(match_id: int):
    from db.models import Match
    async with SessionLocal() as db:
        result = await db.execute(select(Match).where(Match.id == match_id))
        m = result.scalar_one_or_none()
        if not m:
            raise HTTPException(404, "Match not found")
        return _match_dict(m)


# -------- Предикт --------

@app.get("/api/predict")
async def predict_match(
    team1: str,
    team2: str,
    game: str = "cs2",
    match_id: Optional[int] = None,
):
    """Полный предикт по матчу."""
    import sys
    sys.path.insert(0, str(BASE_DIR))

    from aggregator.aggregator import Aggregator
    from analyzer.predictor import predict

    async with SessionLocal() as db:
        agg = Aggregator(db)
        report = await agg.get_match_report(team1, team2, game)
        t1 = report.team1_stats
        t2 = report.team2_stats

        pred = predict(
            team1=team1,
            team2=team2,
            team1_form=t1.form if t1 else "",
            team2_form=t2.form if t2 else "",
            team1_rating=t1.rating if t1 else None,
            team2_rating=t2.rating if t2 else None,
            h2h_matches=report.head_to_head,
        )

        def _team_stats(ts):
            if not ts:
                return None
            recent = []
            for m in ts.recent_matches[:5]:
                rm = dict(m)
                if isinstance(rm.get("date"), datetime):
                    rm["date"] = rm["date"].isoformat()
                recent.append(rm)
            return {
                "rating": ts.rating,
                "wins": ts.wins,
                "losses": ts.losses,
                "form": ts.form,
                "recent_matches": recent,
                "players": ts.players[:6],
            }

        # H2H даты
        h2h = []
        for m in report.head_to_head[:10]:
            rm = dict(m)
            if isinstance(rm.get("date"), datetime):
                rm["date"] = rm["date"].isoformat()
            h2h.append(rm)

        return {
            "team1": team1,
            "team2": team2,
            "game": game,
            "winner": pred.winner,
            "team1_prob": pred.team1_prob,
            "team2_prob": pred.team2_prob,
            "confidence": pred.confidence,
            "reasoning": pred.reasoning,
            "team1_stats": _team_stats(t1),
            "team2_stats": _team_stats(t2),
            "head_to_head": h2h,
            "tournament": report.tournament,
            "match_format": report.match_format,
            "scheduled_at": report.scheduled_at.isoformat() if report.scheduled_at else None,
        }


# -------- Предикты на сегодня --------

@app.get("/api/today")
async def today_predictions(game: Optional[str] = None):
    """Предикты по всем матчам ближайших 36 часов."""
    from db.models import Match, VirtualBet
    from aggregator.aggregator import Aggregator
    from analyzer.predictor import predict

    async with SessionLocal() as db:
        now = datetime.utcnow()
        filters = [
            Match.status.in_(["upcoming", "live"]),
            Match.scheduled_at >= now - timedelta(hours=3),
            Match.scheduled_at <= now + timedelta(hours=36),
        ]
        if game:
            filters.append(Match.game == game)

        result = await db.execute(
            select(Match).where(and_(*filters)).order_by(Match.scheduled_at).limit(30)
        )
        matches = result.scalars().all()

        agg = Aggregator(db)
        out = []

        for m in matches:
            if not m.team1_name or not m.team2_name:
                continue
            if "TBD" in (m.team1_name.upper(), m.team2_name.upper()):
                continue
            try:
                report = await agg.get_match_report(m.team1_name, m.team2_name, m.game)
                t1 = report.team1_stats
                t2 = report.team2_stats

                pred = predict(
                    team1=m.team1_name,
                    team2=m.team2_name,
                    team1_form=t1.form if t1 else "",
                    team2_form=t2.form if t2 else "",
                    team1_rating=t1.rating if t1 else None,
                    team2_rating=t2.rating if t2 else None,
                    h2h_matches=report.head_to_head,
                )

                bet_res = await db.execute(
                    select(VirtualBet).where(VirtualBet.match_id == m.id)
                )
                existing_bet = bet_res.scalar_one_or_none()

                out.append({
                    "match": _match_dict(m),
                    "prediction": {
                        "winner": pred.winner,
                        "team1_prob": pred.team1_prob,
                        "team2_prob": pred.team2_prob,
                        "confidence": pred.confidence,
                        "reasoning": pred.reasoning,
                    },
                    "team1_form": t1.form if t1 else "",
                    "team2_form": t2.form if t2 else "",
                    "team1_rating": t1.rating if t1 else None,
                    "team2_rating": t2.rating if t2 else None,
                    "h2h_count": len(report.head_to_head),
                    "bet": {
                        "bet_on": existing_bet.bet_on,
                        "bet_team": existing_bet.bet_team_name,
                        "odds": existing_bet.odds,
                        "confidence": existing_bet.confidence,
                        "status": existing_bet.status,
                    } if existing_bet else None,
                })
            except Exception as ex:
                logger.warning("predict error %s vs %s: %s", m.team1_name, m.team2_name, ex)
                out.append({"match": _match_dict(m), "prediction": None, "error": str(ex)})

        return out


# -------- Ставки --------

@app.get("/api/bets/stats")
async def bets_stats():
    from bets.virtual_bets import get_bet_stats
    async with SessionLocal() as db:
        stats = await get_bet_stats(db)
        stats["recent"] = [_bet_dict(b) for b in stats.get("recent", [])]
        return stats


@app.get("/api/bets/list")
async def bets_list(
    status: Optional[str] = None,
    game: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    from db.models import VirtualBet
    async with SessionLocal() as db:
        q = select(VirtualBet)
        if status:
            q = q.where(VirtualBet.status == status)
        if game:
            q = q.where(VirtualBet.game == game)
        q = q.order_by(desc(VirtualBet.created_at)).limit(limit)
        result = await db.execute(q)
        return [_bet_dict(b) for b in result.scalars().all()]


@app.get("/api/bets/value")
async def bets_value(
    game: Optional[str] = None,
    limit: int = Query(100, ge=1, le=300),
):
    """Только value-ставки (с реальным перевесом edge), + сводка по ним."""
    from db.models import VirtualBet
    async with SessionLocal() as db:
        q = select(VirtualBet).where(VirtualBet.edge.isnot(None))
        if game:
            q = q.where(VirtualBet.game == game)
        result = await db.execute(q.order_by(desc(VirtualBet.created_at)).limit(limit))
        bets = result.scalars().all()

        settled = [b for b in bets if b.status in ("won", "lost")]
        won = [b for b in settled if b.status == "won"]
        staked = sum(b.stake for b in settled)
        profit = sum(b.profit for b in settled if b.profit is not None)
        avg_edge = (sum(b.edge for b in bets) / len(bets)) if bets else 0.0

        summary = {
            "total": len(bets),
            "pending": sum(1 for b in bets if b.status == "pending"),
            "won": len(won),
            "lost": len(settled) - len(won),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi": round(profit / staked * 100, 2) if staked > 0 else 0.0,
            "winrate": round(len(won) / len(settled) * 100, 1) if settled else 0.0,
            "avg_edge": round(avg_edge * 100, 2),
        }
        # сортируем выдачу: pending по убыванию edge сверху, потом сведённые
        bets_sorted = sorted(
            bets,
            key=lambda b: (b.status != "pending", -(b.edge or 0)),
        )
        return {"summary": summary, "bets": [_bet_dict(b) for b in bets_sorted]}


# -------- Команды --------

@app.get("/api/teams")
async def teams_list(
    game: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    min_games: int = Query(10, ge=0, le=100),
):
    from db.models import Team, Match
    async with SessionLocal() as db:
        q = select(Team)
        if game:
            q = q.where(Team.game == game)
        if search:
            q = q.where(Team.name.ilike(f"%{search}%"))

        # Для Dota2 отсеиваем команды с малым числом сыгранных матчей на про-сцене.
        # Считаем реальные завершённые матчи (Team.wins/losses ненадёжны — агрегат за всё время).
        if game == "dota2" and min_games > 0:
            games_count = (
                select(func.count(Match.id))
                .where(
                    Match.game == "dota2",
                    Match.status == "finished",
                    or_(Match.team1_name == Team.name, Match.team2_name == Team.name),
                )
                .correlate(Team)
                .scalar_subquery()
            )
            q = q.where(games_count >= min_games)

        # Для CS2 сортируем по HLTV рейтингу (если есть), иначе по обычному
        if game == "cs2":
            q = q.order_by(desc(Team.hltv_rating).nullslast(), desc(Team.rating)).limit(limit)
        else:
            q = q.order_by(desc(Team.rating).nullslast()).limit(limit)
        result = await db.execute(q)
        return [_team_dict(t) for t in result.scalars().all()]


@app.get("/api/team/{team_name}")
async def team_detail(team_name: str, game: str = "cs2"):
    from aggregator.aggregator import Aggregator
    async with SessionLocal() as db:
        agg = Aggregator(db)
        report = await agg.get_team_report(team_name, game)
        if not report:
            raise HTTPException(404, "Team not found")

        recent = []
        for m in report.recent_matches:
            rm = dict(m)
            if isinstance(rm.get("date"), datetime):
                rm["date"] = rm["date"].isoformat()
            recent.append(rm)

        h2h = {}
        for k, v in report.head_to_head.items():
            vd = dict(v)
            h2h[k] = vd

        return {
            "name": report.name,
            "game": report.game,
            "rating": report.rating,
            "wins": report.wins,
            "losses": report.losses,
            "form": report.form,
            "players": report.players,
            "recent_matches": recent,
            "head_to_head": h2h,
            "sources": report.sources,
            "last_patch": {
                "version": report.last_patch["version"],
                "released_at": report.last_patch["released_at"].isoformat()
                    if report.last_patch.get("released_at") else None,
                "url": report.last_patch.get("url"),
            } if report.last_patch else None,
        }


@app.get("/api/team/{team_name}/matches")
async def team_matches(
    team_name: str,
    game: str = "cs2",
    limit: int = Query(15, ge=1, le=50),
):
    """Последние N завершённых матчей команды с деталями результата."""
    from db.models import Match
    from sqlalchemy import or_
    async with SessionLocal() as db:
        q = select(Match).where(
            Match.game == game,
            Match.status == "finished",
            or_(Match.team1_name == team_name, Match.team2_name == team_name),
            or_(Match.score_team1 > 0, Match.score_team2 > 0),
        ).order_by(desc(Match.scheduled_at)).limit(limit)
        result = await db.execute(q)
        out = []
        for m in result.scalars().all():
            is_t1 = m.team1_name == team_name
            opponent = m.team2_name if is_t1 else m.team1_name
            own_score = (m.score_team1 if is_t1 else m.score_team2) or 0
            opp_score = (m.score_team2 if is_t1 else m.score_team1) or 0
            won = own_score > opp_score
            out.append({
                "id": m.id,
                "opponent": opponent,
                "score_own": own_score,
                "score_opp": opp_score,
                "result": "W" if won else "L",
                "tournament": m.tournament,
                "tier": m.tier if m.tier is not None else 3,
                "match_format": m.match_format,
                "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            })
        return out


# -------- Новостные события --------

@app.get("/api/news/events")
async def news_events(
    game: Optional[str] = None,
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=200),
    team: Optional[str] = None,
):
    from db.models import NewsEvent
    from sqlalchemy import or_
    from datetime import timedelta
    async with SessionLocal() as db:
        now = datetime.utcnow()
        since = now - timedelta(days=days)
        q = select(NewsEvent).where(
            NewsEvent.created_at >= since,
            NewsEvent.valid_until >= now,
        )
        if game:
            q = q.where(or_(NewsEvent.game == game, NewsEvent.game.is_(None)))
        if team:
            q = q.where(NewsEvent.team_name.ilike(f"%{team}%"))
        q = q.order_by(desc(NewsEvent.created_at)).limit(limit)
        result = await db.execute(q)
        events = result.scalars().all()
        return [{"id": e.id, "team": e.team_name, "player": e.player_name,
                 "game": e.game, "event_type": e.event_type, "impact": e.impact,
                 "summary": e.summary, "channel": e.channel_username,
                 "processed_by": e.processed_by,
                 "created_at": e.created_at.isoformat() if e.created_at else None,
                 "valid_until": e.valid_until.isoformat() if e.valid_until else None}
                for e in events]


@app.get("/api/news/messages")
async def news_messages(
    game: Optional[str] = None,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(60, ge=1, le=200),
    team: Optional[str] = None,
):
    from db.models import TelegramMessage
    from sqlalchemy import or_
    from datetime import timedelta
    async with SessionLocal() as db:
        since = datetime.utcnow() - timedelta(hours=hours)
        q = select(TelegramMessage).where(
            TelegramMessage.posted_at >= since,
            TelegramMessage.text.isnot(None),
        )
        if game:
            q = q.where(or_(TelegramMessage.game == game, TelegramMessage.game == "both"))
        if team:
            q = q.where(or_(TelegramMessage.text.ilike(f"%{team}%"),
                            TelegramMessage.mentioned_teams.ilike(f"%{team}%")))
        q = q.order_by(desc(TelegramMessage.posted_at)).limit(limit)
        result = await db.execute(q)
        return [{"id": m.id, "channel": m.channel_username, "text": (m.text or "")[:500],
                 "game": m.game, "teams": m.mentioned_teams,
                 "posted_at": m.posted_at.isoformat() if m.posted_at else None}
                for m in result.scalars().all()]


@app.get("/api/news/team/{team_name}")
async def team_news_endpoint(team_name: str, game: Optional[str] = None, days: int = 7):
    from db.models import NewsEvent, TelegramMessage
    from sqlalchemy import or_
    from datetime import timedelta
    async with SessionLocal() as db:
        now = datetime.utcnow()
        since = now - timedelta(days=days)
        words = [w for w in team_name.lower().split()
                 if len(w) > 2 and w not in ("team", "gaming", "esports", "club")]
        search = words[0] if words else team_name.lower()

        eq = select(NewsEvent).where(
            NewsEvent.created_at >= since, NewsEvent.valid_until >= now,
            NewsEvent.team_name.ilike(f"%{search}%"),
        )
        if game:
            eq = eq.where(or_(NewsEvent.game == game, NewsEvent.game.is_(None)))
        er = await db.execute(eq.order_by(desc(NewsEvent.created_at)).limit(10))

        mq = select(TelegramMessage).where(
            TelegramMessage.posted_at >= since,
            or_(TelegramMessage.text.ilike(f"%{search}%"),
                TelegramMessage.mentioned_teams.ilike(f"%{search}%")),
        ).order_by(desc(TelegramMessage.posted_at)).limit(5)
        mr = await db.execute(mq)

        return {
            "team": team_name,
            "events": [{"event_type": e.event_type, "impact": e.impact,
                        "summary": e.summary, "player": e.player_name,
                        "created_at": e.created_at.isoformat() if e.created_at else None}
                       for e in er.scalars().all()],
            "messages": [{"channel": m.channel_username, "text": (m.text or "")[:300],
                          "posted_at": m.posted_at.isoformat() if m.posted_at else None}
                         for m in mr.scalars().all()],
        }


# -------- Патч --------

@app.get("/api/patch/{game}")
async def patch_latest(game: str):
    from aggregator.aggregator import Aggregator
    async with SessionLocal() as db:
        agg = Aggregator(db)
        patch = await agg._get_last_patch(game)
        if not patch:
            raise HTTPException(404, "No patch data")
        return {
            "game": game,
            "version": patch["version"],
            "released_at": patch["released_at"].isoformat() if patch.get("released_at") else None,
            "url": patch.get("url"),
            "summary": patch.get("summary"),
        }


# -------- Системная статистика --------

@app.get("/api/stats/summary")
async def system_summary():
    from db.models import Match, Team, VirtualBet
    async with SessionLocal() as db:
        total_m = (await db.execute(select(func.count(Match.id)))).scalar() or 0
        upcoming_m = (await db.execute(
            select(func.count(Match.id)).where(Match.status == "upcoming")
        )).scalar() or 0
        finished_m = (await db.execute(
            select(func.count(Match.id)).where(Match.status == "finished")
        )).scalar() or 0
        live_m = (await db.execute(
            select(func.count(Match.id)).where(Match.status == "live")
        )).scalar() or 0

        teams_count = (await db.execute(select(func.count(Team.id)))).scalar() or 0
        bets_total = (await db.execute(select(func.count(VirtualBet.id)))).scalar() or 0
        bets_won = (await db.execute(
            select(func.count(VirtualBet.id)).where(VirtualBet.status == "won")
        )).scalar() or 0
        bets_pending = (await db.execute(
            select(func.count(VirtualBet.id)).where(VirtualBet.status == "pending")
        )).scalar() or 0

        return {
            "matches": {
                "total": total_m,
                "upcoming": upcoming_m,
                "finished": finished_m,
                "live": live_m,
            },
            "teams": teams_count,
            "bets": {
                "total": bets_total,
                "won": bets_won,
                "pending": bets_pending,
            },
            "updated_at": datetime.utcnow().isoformat(),
        }


# -------- Маркеты (аналитика ставок) --------

@app.get("/api/markets/by_teams")
async def predict_markets_by_teams(
    team1: str,
    team2: str,
    game: str = "dota2",
):
    """Аналитика маркетов по именам команд (без match_id)."""
    from analyzer.market_predictor import predict_markets
    async with SessionLocal() as db:
        win_prob = 0.5
        try:
            from analyzer.analyzer import MatchAnalyzer
            analyzer = MatchAnalyzer(db)
            pred = await analyzer.quick_predict(team1, team2, game)
            win_prob = pred.get("team1_prob", 0.5)
        except Exception:
            pass
        return await predict_markets(db, team1, team2, game, win_prob)


@app.get("/api/markets/{match_id}")
async def match_markets(match_id: int):
    """Полная аналитика маркетов для матча — тоталы, форы, первая кровь и т.д."""
    from db.models import Match
    from analyzer.market_predictor import predict_markets
    async with SessionLocal() as db:
        m = await db.get(Match, match_id)
        if not m:
            raise HTTPException(404, "Match not found")

        # Получаем предсказание вероятности победы
        win_prob = 0.5
        try:
            from analyzer.analyzer import MatchAnalyzer
            analyzer = MatchAnalyzer(db)
            pred = await analyzer.quick_predict(m.team1_name, m.team2_name, m.game)
            win_prob = pred.get("team1_prob", 0.5)
        except Exception:
            pass

        result = await predict_markets(db, m.team1_name, m.team2_name, m.game, win_prob)
        result["match_id"] = match_id
        result["scheduled_at"] = m.scheduled_at.isoformat() if m.scheduled_at else None
        result["tournament"] = m.tournament
        return result



@app.get("/api/stats/detail/{game}")
async def detail_stats_summary(game: str, team: Optional[str] = None, limit: int = 20):
    """Детальная статистика игр (kills, towers, roshans)."""
    from db.models import MatchDetailStats
    async with SessionLocal() as db:
        q = select(MatchDetailStats).where(MatchDetailStats.game == game)
        if team:
            norm = team.lower()
            words = [w for w in norm.split() if len(w) > 2]
            search = words[0] if words else norm
            q = q.where(or_(
                MatchDetailStats.team1_name.ilike(f"%{search}%"),
                MatchDetailStats.team2_name.ilike(f"%{search}%"),
            ))
        q = q.order_by(desc(MatchDetailStats.match_date)).limit(limit)
        res = await db.execute(q)
        rows = res.scalars().all()
        return [{
            "id": r.id,
            "team1": r.team1_name,
            "team2": r.team2_name,
            "winner": r.winner,
            "total_kills": r.total_kills,
            "team1_kills": r.team1_kills,
            "team2_kills": r.team2_kills,
            "total_towers": r.total_towers,
            "total_roshans": r.total_roshans,
            "duration_min": round(r.duration_seconds / 60, 1) if r.duration_seconds else None,
            "had_megacreeps": r.had_megacreeps,
            "first_blood_team": r.first_blood_team,
            "match_date": r.match_date.isoformat() if r.match_date else None,
            "tournament": r.tournament,
        } for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, reload=True)
