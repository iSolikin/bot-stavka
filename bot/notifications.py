"""
Модуль уведомлений о предстоящих матчах.
Проверяет матчи которые начнутся через ~60 минут и рассылает
подписчикам команд которые в них участвуют.
"""
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from aggregator.aggregator import normalize_team_name
from bot.formatters.telegram_format import escape_md as e
from db.models import Match, MatchNotification, Subscription, User

logger = logging.getLogger(__name__)

# За сколько минут до матча слать уведомление
NOTIFY_BEFORE_MINUTES = 60
# Окно проверки — чтобы не пропустить матч между двумя запусками джоба
WINDOW_MINUTES = 15


async def send_match_notifications(db: AsyncSession, bot: Bot) -> int:
    """
    Найти матчи которые начнутся через NOTIFY_BEFORE_MINUTES минут
    и разослать уведомления подписчикам.
    Возвращает кол-во отправленных уведомлений.
    """
    now = datetime.utcnow()
    notify_from = now + timedelta(minutes=NOTIFY_BEFORE_MINUTES - WINDOW_MINUTES)
    notify_until = now + timedelta(minutes=NOTIFY_BEFORE_MINUTES + WINDOW_MINUTES)

    # Матчи в нужном окне
    result = await db.execute(
        select(Match).where(
            and_(
                Match.status == "upcoming",
                Match.scheduled_at >= notify_from,
                Match.scheduled_at <= notify_until,
            )
        )
    )
    matches = result.scalars().all()

    if not matches:
        return 0

    sent_total = 0

    for match in matches:
        # Нормализованные ключи обеих команд
        team1_key = normalize_team_name(match.team1_name)
        team2_key = normalize_team_name(match.team2_name)

        # Подписчики на любую из двух команд с нужной игрой
        subs_result = await db.execute(
            select(Subscription).where(
                and_(
                    Subscription.game == match.game,
                    or_(
                        Subscription.team_key == team1_key,
                        Subscription.team_key == team2_key,
                        # Частичное совпадение — на случай разных написаний
                        Subscription.team_key.ilike(f"%{team1_key}%"),
                        Subscription.team_key.ilike(f"%{team2_key}%"),
                    )
                )
            )
        )
        subscriptions = subs_result.scalars().all()

        if not subscriptions:
            continue

        for sub in subscriptions:
            # Проверяем не слали ли уже
            notif_check = await db.execute(
                select(MatchNotification).where(
                    and_(
                        MatchNotification.match_id == match.id,
                        MatchNotification.user_id == sub.user_id,
                    )
                )
            )
            if notif_check.scalar_one_or_none():
                continue  # уже отправляли

            # Получаем telegram_id пользователя
            user_result = await db.execute(
                select(User).where(User.id == sub.user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user or not user.is_active:
                continue

            # Формируем сообщение
            text = _format_notification(match)

            try:
                await bot.send_message(user.telegram_id, text)

                # Записываем что отправили
                notif = MatchNotification(match_id=match.id, user_id=sub.user_id)
                db.add(notif)
                sent_total += 1

            except Exception as ex:
                logger.warning(
                    "Failed to send notification to %s: %s",
                    user.telegram_id, ex
                )

    if sent_total:
        await db.commit()

    logger.info("Notifications sent: %d", sent_total)
    return sent_total


def _format_notification(match: Match) -> str:
    t1 = e(match.team1_name)
    t2 = e(match.team2_name)
    game = e(match.game.upper())

    lines = [f"🔔 *Матч через час\\!* \\[{game}\\]"]
    lines.append(f"⚔️ *{t1}* vs *{t2}*")

    if match.tournament:
        lines.append(f"🏆 {e(match.tournament)}")

    if match.match_format:
        lines.append(f"📋 {e(match.match_format)}")

    if match.scheduled_at:
        lines.append(f"🕐 {e(match.scheduled_at.strftime('%d.%m.%Y %H:%M'))} UTC")

    if match.match_url:
        lines.append(f"\n[Смотреть матч]({match.match_url})")

    lines.append(f"\n_Используй /match {e(match.team1_name)} vs {e(match.team2_name)} для анализа_")

    return "\n".join(lines)
