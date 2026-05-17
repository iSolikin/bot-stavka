"""
Анализатор: принимает запрос, собирает данные через Aggregator,
формирует структурированный текстовый отчёт.
Никаких прогнозов — только факты и цифры.
"""
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from aggregator.aggregator import Aggregator, MatchReport, PlayerReport, TeamReport

logger = logging.getLogger(__name__)


class Analyzer:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.aggregator = Aggregator(db)

    async def team_report(self, team_name: str, game: str) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        report = await self.aggregator.get_team_report(team_name, game)
        if not report:
            return f"Команда *{e(team_name)}* не найдена в базе данных\\."
        # Если команды нет в Teams и нет матчей — тоже не найдена
        if not report.sources and not report.recent_matches:
            return f"Команда *{e(team_name)}* не найдена в базе данных\\."
        return self._format_team_report(report)

    async def match_report(self, team1: str, team2: str, game: str) -> str:
        report = await self.aggregator.get_match_report(team1, team2, game)
        return self._format_match_report(report)

    async def full_match_analysis(self, team1: str, team2: str, game: str, match_id: int | None = None) -> str:
        """Полный анализ матча с предиктом — для кнопочного выбора матча."""
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        from analyzer.predictor import predict
        from collectors.odds import get_odds_for_game
        from collectors.odds import OddsCollector

        report = await self.aggregator.get_match_report(team1, team2, game)
        t1stats = report.team1_stats
        t2stats = report.team2_stats

        # Кэфы
        odds_list = await get_odds_for_game(game)
        o1, o2 = None, None
        bookmaker = ""
        if odds_list:
            oc = OddsCollector(None)  # HTTP не нужен для find_odds (синхронный метод)
            o1, o2 = oc.find_odds(team1, team2, odds_list)
            bookmaker = odds_list[0].get("bookmaker", "")

        # Предикт
        pred = predict(
            team1=team1,
            team2=team2,
            team1_form=t1stats.form if t1stats else "",
            team2_form=t2stats.form if t2stats else "",
            team1_rating=t1stats.rating if t1stats else None,
            team2_rating=t2stats.rating if t2stats else None,
            h2h_matches=report.head_to_head,
            team1_odds=o1,
            team2_odds=o2,
        )

        # Авто-ставка в демо-режиме
        try:
            from bets.virtual_bets import place_auto_bet
            await place_auto_bet(
                db=self.db,
                match_id=match_id,
                team1=team1,
                team2=team2,
                game=game,
                tournament=report.tournament,
                scheduled_at=report.scheduled_at,
                pred=pred,
                bookmaker_odds1=o1,
                bookmaker_odds2=o2,
            )
        except Exception as _bet_err:
            logger.warning("Auto-bet failed: %s", _bet_err)

        return self._format_full_analysis(report, pred, o1, o2, bookmaker, game)

    async def quick_predict(
        self,
        team1: str,
        team2: str,
        game: str,
        match_id: int | None = None,
        scheduled_at=None,
        tournament: str | None = None,
    ):
        """Быстрый предикт без полного форматирования — только данные из БД.
        Возвращает (Prediction, MatchReport). Ставит авто-ставку.
        """
        from analyzer.predictor import predict, Prediction

        report = await self.aggregator.get_match_report(team1, team2, game)
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

        # Авто-ставка
        try:
            from bets.virtual_bets import place_auto_bet
            await place_auto_bet(
                db=self.db,
                match_id=match_id,
                team1=team1,
                team2=team2,
                game=game,
                tournament=tournament or report.tournament,
                scheduled_at=scheduled_at or report.scheduled_at,
                pred=pred,
            )
        except Exception as _e:
            logger.warning("Auto-bet failed for %s vs %s: %s", team1, team2, _e)

        return pred, report

    async def matches_today(self, game: str) -> list[dict]:
        """Матчи на сегодня — для списка с кнопками."""
        from datetime import timedelta
        from sqlalchemy import select, and_
        from datetime import datetime as dt
        from db.models import Match

        now = dt.utcnow()
        until = now + timedelta(hours=36)
        from_time = now - timedelta(hours=3)  # включаем live-матчи которые идут сейчас

        result = await self.db.execute(
            select(Match).where(
                and_(
                    Match.game == game,
                    Match.status.in_(["upcoming", "live"]),
                    Match.scheduled_at >= from_time,
                    Match.scheduled_at <= until,
                )
            ).order_by(Match.scheduled_at).limit(15)
        )
        matches = result.scalars().all()
        return [
            {
                "id": m.id,
                "team1": m.team1_name,
                "team2": m.team2_name,
                "tournament": m.tournament,
                "scheduled_at": m.scheduled_at,
                "match_format": m.match_format,
            }
            for m in matches
        ]

    async def upcoming_matches(self, game: str, hours: int = 48) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        matches = await self.aggregator.get_upcoming_matches(game, hours)
        if not matches:
            return f"Матчей *{e(game.upper())}* на ближайшие {hours} часов не найдено\\."
        return self._format_upcoming(matches, game, hours)

    async def player_report(self, nickname: str, game: str | None = None) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        report = await self.aggregator.get_player_report(nickname, game)
        if not report:
            return f"Игрок *{e(nickname)}* не найден в базе данных\\."
        return self._format_player_report(report)

    async def patch_report(self, game: str) -> str:
        """Отчёт по последнему патчу."""
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        patch = await self.aggregator._get_last_patch(game)
        if not patch:
            return f"Информация о патчах {game.upper()} пока отсутствует\\."

        lines = [f"🔧 *Патч {e(game.upper())}*\n"]
        lines.append(f"Версия: *{e(patch['version'])}*")
        if patch.get("released_at"):
            lines.append(f"Дата: {e(patch['released_at'].strftime('%d.%m.%Y'))}")
        if patch.get("summary"):
            lines.append(f"\n{e(patch['summary'])}")
        if patch.get("url"):
            lines.append(f"\n[Читать подробнее]({patch['url']})")

        return "\n".join(lines)

    # --- Форматирование ---

    def _format_team_report(self, r: TeamReport) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        game_label = r.game.upper()
        lines = [f"🏆 *{e(r.name)}* \\[{e(game_label)}\\]\n"]

        if r.rating is not None or r.wins or r.losses:
            lines.append("📊 *Статистика*")
            if r.rating is not None:
                lines.append(f"  Рейтинг: *{e(f'{r.rating:.0f}')}*")
            if r.wins or r.losses:
                total = r.wins + r.losses
                wr = (r.wins / total * 100) if total else 0
                lines.append(f"  W/L: *{r.wins}/{r.losses}* \\({e(f'{wr:.1f}')}%\\)")
            if r.form:
                lines.append(f"  Форма: `{e(r.form)}`")

        if r.players:
            lines.append("")
            lines.append("👥 *Состав*")
            for p in r.players:
                line = f"  • *{e(p['nickname'])}*"
                if p.get("real_name"):
                    line += f" — {e(p['real_name'])}"
                if p.get("rating"):
                    rating_str = e(f"{p['rating']:.2f}")
                    line += f" \\({rating_str} рейтинг\\)"
                lines.append(line)

        if r.recent_matches:
            lines.append("")
            lines.append("📋 *Последние матчи*")
            for m in r.recent_matches[:5]:
                date_str = e(fmt_time(m["date"], "%d.%m")) if m.get("date") else "—"
                t1 = e(m["team1"])
                t2 = e(m["team2"])
                score = e(m.get("score", "?:?"))
                lines.append(f"  {date_str}  *{t1}* {score} *{t2}*")

        if r.head_to_head:
            lines.append("")
            lines.append("⚔️ *H2H с соперниками*")
            sorted_h2h = sorted(
                r.head_to_head.items(),
                key=lambda x: x[1]["wins"] + x[1]["losses"],
                reverse=True,
            )[:5]
            for _, data in sorted_h2h:
                opp = e(data["opponent"])
                lines.append(f"  vs *{opp}*: {data['wins']}W / {data['losses']}L")

        if r.last_patch:
            lines.append("")
            patch = r.last_patch
            date_str = e(fmt_time(patch["released_at"], "%d.%m.%Y")) if patch.get("released_at") else "—"
            lines.append(f"🔧 Патч: *{e(patch['version'])}* от {date_str}")

        if r.telegram_mentions:
            lines.append("")
            lines.append("📢 *Упоминания в Telegram*")
            for msg in r.telegram_mentions[:3]:
                date_str = e(fmt_time(msg["posted_at"])) if msg.get("posted_at") else "—"
                preview = e(msg["text"][:80].replace("\n", " "))
                lines.append(f"  \\[{date_str}\\] @{e(msg['channel'])}: {preview}…")

        return "\n".join(lines)

    def _format_match_report(self, r: MatchReport) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        game_label = r.game.upper()
        t1 = e(r.team1)
        t2 = e(r.team2)
        lines = [f"⚔️ *{t1}* vs *{t2}* \\[{e(game_label)}\\]\n"]

        if r.tournament:
            lines.append(f"🏆 {e(r.tournament)}")
        if r.match_format:
            lines.append(f"📋 Формат: {e(r.match_format)}")
        if r.scheduled_at:
            lines.append(f"🕐 {e(fmt_time(r.scheduled_at, '%d.%m.%Y %H:%M'))} ЕКБ")

        for emoji, label, stats in [("🔵", r.team1, r.team1_stats), ("🔴", r.team2, r.team2_stats)]:
            lines.append("")
            lines.append(f"{emoji} *{e(label)}*")
            if stats:
                if stats.rating is not None:
                    lines.append(f"  Рейтинг: *{e(f'{stats.rating:.0f}')}*")
                if stats.wins or stats.losses:
                    total = stats.wins + stats.losses
                    wr = (stats.wins / total * 100) if total else 0
                    lines.append(f"  W/L: *{stats.wins}/{stats.losses}* \\({e(f'{wr:.1f}')}%\\)")
                if stats.form:
                    lines.append(f"  Форма: `{e(stats.form)}`")
                if stats.players:
                    nicks = e(", ".join(p["nickname"] for p in stats.players[:5]))
                    lines.append(f"  Состав: {nicks}")
            else:
                lines.append("  _Данные отсутствуют_")

        if r.head_to_head:
            lines.append("")
            lines.append("📊 *История встреч*")
            for m in r.head_to_head[:5]:
                date_str = e(fmt_time(m["date"], "%d.%m.%Y")) if m.get("date") else "—"
                mt1 = e(m["team1"])
                mt2 = e(m["team2"])
                score = e(m.get("score", "?:?"))
                lines.append(f"  {date_str}  *{mt1}* {score} *{mt2}*")

        if r.last_patch:
            patch = r.last_patch
            date_str = e(fmt_time(patch["released_at"], "%d.%m.%Y")) if patch.get("released_at") else "—"
            lines.append(f"\n🔧 Патч: *{e(patch['version'])}* от {date_str}")

        return "\n".join(lines)

    def _format_full_analysis(self, r: MatchReport, pred, o1, o2, bookmaker: str, game: str) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        t1 = e(r.team1)
        t2 = e(r.team2)
        gl = e(game.upper())

        lines = [f"🔍 *Анализ матча* \\[{gl}\\]"]
        lines.append(f"⚔️ *{t1}* vs *{t2}*")

        if r.tournament:
            lines.append(f"🏆 {e(r.tournament)}")
        if r.match_format:
            lines.append(f"📋 {e(r.match_format)}")
        if r.scheduled_at:
            lines.append(f"🕐 {e(fmt_time(r.scheduled_at))} ЕКБ")

        # Карты CS2
        if game == "cs2":
            lines.append("\n🗺 *Карты:* не объявлены")

        lines.append("")

        # Статистика двух команд
        for emoji, team_name, stats in [("🔵", r.team1, r.team1_stats), ("🔴", r.team2, r.team2_stats)]:
            lines.append(f"{emoji} *{e(team_name)}*")
            if stats:
                if stats.form:
                    lines.append(f"  Форма: `{e(stats.form)}`")
                if stats.wins or stats.losses:
                    total = stats.wins + stats.losses
                    wr = (stats.wins / total * 100) if total else 0
                    lines.append(f"  W/L: {stats.wins}/{stats.losses} \\({e(f'{wr:.0f}')}%\\)")
                if stats.rating:
                    lines.append(f"  Рейтинг: {e(f'{stats.rating:.0f}')}")
                if stats.players:
                    nicks = e(", ".join(p["nickname"] for p in stats.players[:5]))
                    lines.append(f"  Состав: {nicks}")
                if stats.recent_matches:
                    lines.append(f"  Последние матчи:")
                    for m in stats.recent_matches[:3]:
                        d = e(fmt_time(m["date"], "%d.%m")) if m.get("date") else "—"
                        lines.append(f"    {d} *{e(m['team1'])}* {e(m.get('score','?:?'))} *{e(m['team2'])}*")
            else:
                lines.append("  _Нет данных_")
            lines.append("")

        # H2H
        if r.head_to_head:
            lines.append("📊 *История встреч*")
            for m in r.head_to_head[:5]:
                d = e(fmt_time(m["date"], "%d.%m.%Y")) if m.get("date") else "—"
                lines.append(f"  {d}  *{e(m['team1'])}* {e(m.get('score','?:?'))} *{e(m['team2'])}*")
            lines.append("")

        # Патч
        if r.last_patch:
            patch = r.last_patch
            d = e(fmt_time(patch["released_at"], "%d.%m.%Y")) if patch.get("released_at") else "—"
            lines.append(f"🔧 Актуальный патч: *{e(patch['version'])}* от {d}")
            lines.append("")

        # Кэфы
        if o1 and o2:
            bk = e(bookmaker) if bookmaker else "букмекер"
            lines.append(f"💰 *Кэфы* \\({bk}\\)")
            lines.append(f"  {t1}: *{e(f'{o1:.2f}')}*  |  {t2}: *{e(f'{o2:.2f}')}*")
            lines.append("")

        # Предикт
        conf_emoji = {"низкая": "🟡", "средняя": "🟠", "высокая": "🟢"}.get(pred.confidence, "⚪")
        p1pct = e(f"{pred.team1_prob * 100:.0f}")
        p2pct = e(f"{pred.team2_prob * 100:.0f}")
        winner = e(pred.winner)

        lines.append("🤖 *Предикт бота*")
        lines.append(f"  {t1}: *{p1pct}%*  vs  {t2}: *{p2pct}%*")
        lines.append(f"  Победитель: 👉 *{winner}*")
        lines.append(f"  Уверенность: {conf_emoji} {e(pred.confidence)}")
        lines.append("")
        lines.append("_На основе:_")
        for r_line in pred.reasoning:
            lines.append(f"  _{e(r_line)}_")

        return "\n".join(lines)

    def _format_player_report(self, r: PlayerReport) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        game_label = e(r.game.upper()) if r.game else "?"
        lines = [f"👤 *{e(r.nickname)}* \\[{game_label}\\]\n"]

        if r.real_name:
            lines.append(f"Имя: {e(r.real_name)}")
        if r.country:
            lines.append(f"Страна: {e(r.country)}")
        if r.team_name:
            lines.append(f"Команда: *{e(r.team_name)}*")
        if r.rating is not None:
            lines.append(f"Рейтинг: *{e(f'{r.rating:.2f}')}*")

        if r.telegram_mentions:
            lines.append("")
            lines.append("📢 *Упоминания в Telegram*")
            for msg in r.telegram_mentions[:3]:
                date_str = e(msg["posted_at"].strftime("%d.%m %H:%M")) if msg.get("posted_at") else "—"
                preview = e(msg["text"][:80].replace("\n", " "))
                lines.append(f"  \\[{date_str}\\] @{e(msg['channel'])}: {preview}…")

        return "\n".join(lines)

    def _format_upcoming(self, matches: list[dict], game: str, hours: int) -> str:
        from bot.formatters.telegram_format import escape_md as e, fmt_time
        game_label = game.upper()
        lines = [f"📅 *Матчи {e(game_label)}* — ближайшие {hours} часов\n"]

        current_tournament = None
        for m in matches:
            tournament = m.get("tournament") or "Без турнира"
            if tournament != current_tournament:
                if current_tournament is not None:
                    lines.append("")
                lines.append(f"🏆 *{e(tournament)}*")
                current_tournament = tournament

            t1 = e(m["team1"])
            t2 = e(m["team2"])
            fmt = m.get("match_format") or ""
            fmt_str = f" · {e(fmt)}" if fmt else ""

            is_live = m.get("status") == "live"
            if is_live:
                time_str = "🔴 LIVE"
            elif m.get("scheduled_at"):
                time_str = e(fmt_time(m["scheduled_at"])) + " ЕКБ"
            else:
                time_str = "—"

            lines.append(f"  ⚔️ *{t1}* vs *{t2}*{fmt_str}")
            lines.append(f"  🕐 {time_str}")

        return "\n".join(lines)
