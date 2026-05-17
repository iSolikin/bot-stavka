"""
Подписки на уведомления о матчах команды.
/sub NaVi cs2   — подписаться
/unsub NaVi cs2 — отписаться
/mysubs         — мои подписки
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Subscription, User
from aggregator.aggregator import normalize_team_name

router = Router()

GAME_ALIASES = {
    "cs": "cs2", "cs2": "cs2",
    "dota": "dota2", "dota2": "dota2", "d2": "dota2",
}

MAX_SUBS = 10


def _parse_team_game(query: str) -> tuple[str, str, str]:
    """'NaVi cs2' -> (key='navi', display='NaVi', game='cs2')"""
    parts = query.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lower() in GAME_ALIASES:
        display = parts[0].strip()
        return normalize_team_name(display), display, GAME_ALIASES[parts[1].lower()]
    display = query.strip()
    return normalize_team_name(display), display, "cs2"


async def _get_or_create_user(db: AsyncSession, tg_user) -> User:
    """Получить или создать запись пользователя."""
    result = await db.execute(select(User).where(User.telegram_id == tg_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        db.add(user)
        await db.flush()
    return user


@router.message(Command("sub"))
async def cmd_sub(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Использование: `/sub Команда \\[игра\\]`\n\n"
            "Примеры:\n"
            "`/sub NaVi cs2`\n"
            "`/sub Spirit dota2`\n\n"
            "Пришлю уведомление за час до матча\\."
        )
        return

    team_key, team_display, game = _parse_team_game(args[1])
    user = await _get_or_create_user(db, message.from_user)

    subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    existing_subs = subs_result.scalars().all()

    if len(existing_subs) >= MAX_SUBS:
        await message.answer(
            f"У тебя уже {MAX_SUBS} подписок — это максимум\\.\n"
            "Используй /unsub чтобы убрать лишние\\."
        )
        return

    dup = next((s for s in existing_subs if s.team_key == team_key and s.game == game), None)
    if dup:
        await message.answer(
            f"Ты уже подписан на *{dup.team_display}* \\[{game.upper()}\\]\\."
        )
        return

    sub = Subscription(user_id=user.id, team_key=team_key, team_display=team_display, game=game)
    db.add(sub)
    await db.commit()

    await message.answer(
        f"✅ Подписка оформлена: *{team_display}* \\[{game.upper()}\\]\n"
        "Уведомлю за 1 час до матча\\."
    )


@router.message(Command("unsub"))
async def cmd_unsub(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Использование: `/unsub Команда \\[игра\\]`\n\n"
            "Посмотреть подписки: /mysubs"
        )
        return

    team_key, _, game = _parse_team_game(args[1])
    user = await _get_or_create_user(db, message.from_user)

    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.team_key == team_key,
            Subscription.game == game,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        await message.answer(f"Подписки на *{team_key}* не найдено\\.")
        return

    await db.delete(sub)
    await db.commit()
    await message.answer(f"✅ Отписался от *{sub.team_display}* \\[{game.upper()}\\]\\.")


@router.message(Command("mysubs"))
async def cmd_mysubs(message: Message, db: AsyncSession) -> None:
    user = await _get_or_create_user(db, message.from_user)
    subs_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at)
    )
    subs = subs_result.scalars().all()

    if not subs:
        await message.answer(
            "У тебя нет подписок\\.\n\n"
            "Подпишись: `/sub NaVi cs2`"
        )
        return

    lines = [f"🔔 *Твои подписки* \\({len(subs)}/{MAX_SUBS}\\):\n"]
    for s in subs:
        lines.append(f"• {s.team_display} \\[{s.game.upper()}\\]")
    lines.append("\nОтписаться: `/unsub Команда игра`")
    await message.answer("\n".join(lines))
