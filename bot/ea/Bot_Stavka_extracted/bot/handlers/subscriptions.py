"""
Подписки на команды.
/subscribe NaVi        — подписаться на NaVi (CS2 по умолчанию)
/subscribe OG dota2    — подписаться на OG в Dota2
/unsubscribe NaVi      — отписаться
/mysubs                — список подписок
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete

from aggregator.aggregator import normalize_team_name
from bot.formatters.telegram_format import escape_md as e
from db.models import Subscription, User

logger = logging.getLogger(__name__)
router = Router()

GAME_ALIASES = {
    "cs": "cs2", "cs2": "cs2",
    "dota": "dota2", "dota2": "dota2", "d2": "dota2",
}

MAX_SUBS = 10  # максимум подписок на пользователя


def _parse_team_game(query: str) -> tuple[str, str]:
    parts = query.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lower() in GAME_ALIASES:
        return parts[0].strip(), GAME_ALIASES[parts[1].lower()]
    return query.strip(), "cs2"


async def _get_or_create_user(db: AsyncSession, tg_user) -> User:
    result = await db.execute(select(User).where(User.telegram_id == tg_user.id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        db.add(user)
        await db.flush()
    return user


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование:\n"
            "`/subscribe NaVi` — CS2\n"
            "`/subscribe OG dota2` — Dota2"
        )
        return

    team_display, game = _parse_team_game(args[1])
    team_key = normalize_team_name(team_display)

    user = await _get_or_create_user(db, message.from_user)

    # Проверяем лимит
    count_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    existing_subs = count_result.scalars().all()

    if len(existing_subs) >= MAX_SUBS:
        await message.answer(
            f"У тебя уже {MAX_SUBS} подписок — максимум\\.\n"
            "Отпишись от чего-нибудь через `/unsubscribe Название`"
        )
        return

    # Проверяем дубликат
    dup = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user.id,
                Subscription.team_key == team_key,
                Subscription.game == game,
            )
        )
    )
    if dup.scalar_one_or_none():
        await message.answer(
            f"Ты уже подписан на *{e(team_display)}* \\[{e(game.upper())}\\]"
        )
        return

    sub = Subscription(
        user_id=user.id,
        team_key=team_key,
        team_display=team_display,
        game=game,
    )
    db.add(sub)
    await db.commit()

    await message.answer(
        f"✅ Подписка оформлена\\!\n"
        f"Буду присылать уведомление за час до матчей *{e(team_display)}* \\[{e(game.upper())}\\]\\.\n\n"
        f"Посмотреть все подписки: /mysubs"
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: `/unsubscribe NaVi` или `/unsubscribe OG dota2`")
        return

    team_display, game = _parse_team_game(args[1])
    team_key = normalize_team_name(team_display)

    user_result = await db.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        await message.answer("Подписок нет\\.")
        return

    result = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user.id,
                Subscription.team_key == team_key,
                Subscription.game == game,
            )
        )
    )
    sub = result.scalar_one_or_none()

    if not sub:
        await message.answer(
            f"Подписки на *{e(team_display)}* \\[{e(game.upper())}\\] не найдено\\."
        )
        return

    await db.delete(sub)
    await db.commit()
    await message.answer(f"✅ Отписался от *{e(team_display)}* \\[{e(game.upper())}\\]")


@router.message(Command("mysubs"))
async def cmd_mysubs(message: Message, db: AsyncSession) -> None:
    user_result = await db.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    user = user_result.scalar_one_or_none()

    if not user:
        await message.answer("У тебя нет подписок\\. Добавь через `/subscribe NaVi`")
        return

    subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.game)
    )
    subs = subs_result.scalars().all()

    if not subs:
        await message.answer("У тебя нет подписок\\. Добавь через `/subscribe NaVi`")
        return

    lines = [f"🔔 *Твои подписки* \\({len(subs)}/{MAX_SUBS}\\):\n"]
    for sub in subs:
        lines.append(f"  • *{e(sub.team_display)}* \\[{e(sub.game.upper())}\\]")

    lines.append("\nОтписаться: `/unsubscribe Название`")

    # Кнопки быстрой отписки
    buttons = []
    for sub in subs:
        buttons.append([InlineKeyboardButton(
            text=f"❌ {sub.team_display} [{sub.game.upper()}]",
            callback_data=f"unsub_{sub.team_key}_{sub.game}"
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("unsub_"))
async def cb_unsubscribe(call: CallbackQuery, db: AsyncSession) -> None:
    """Быстрая отписка по кнопке из /mysubs."""
    parts = call.data.split("_", 2)
    if len(parts) < 3:
        await call.answer("Ошибка")
        return

    team_key = parts[1]
    game = parts[2]

    user_result = await db.execute(
        select(User).where(User.telegram_id == call.from_user.id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        await call.answer("Пользователь не найден")
        return

    result = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user.id,
                Subscription.team_key == team_key,
                Subscription.game == game,
            )
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        team_display = sub.team_display
        await db.delete(sub)
        await db.commit()
        await call.answer(f"Отписался от {team_display}")
    else:
        await call.answer("Подписка не найдена")

    # Обновляем список
    subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.game)
    )
    subs = subs_result.scalars().all()

    if not subs:
        await call.message.edit_text("Подписок больше нет\\. Добавь через `/subscribe NaVi`")
        return

    lines = [f"🔔 *Твои подписки* \\({len(subs)}/{MAX_SUBS}\\):\n"]
    for s in subs:
        lines.append(f"  • *{e(s.team_display)}* \\[{e(s.game.upper())}\\]")

    buttons = []
    for s in subs:
        buttons.append([InlineKeyboardButton(
            text=f"❌ {s.team_display} [{s.game.upper()}]",
            callback_data=f"unsub_{s.team_key}_{s.game}"
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("\n".join(lines), reply_markup=kb)
