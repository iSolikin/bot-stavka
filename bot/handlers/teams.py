from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from analyzer.analyzer import Analyzer
from cache.redis_cache import cache
from bot.formatters.telegram_format import split_message
from bot.keyboards import back_to_menu

router = Router()

GAME_ALIASES = {
    "cs": "cs2", "cs2": "cs2",
    "dota": "dota2", "dota2": "dota2", "d2": "dota2",
}


def _parse_team_and_game(query: str) -> tuple[str, str | None]:
    """Парсит 'NaVi dota2' → ('NaVi', 'dota2'), 'Team Spirit' → ('Team Spirit', None)."""
    parts = query.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lower() in GAME_ALIASES:
        return parts[0].strip(), GAME_ALIASES[parts[1].lower()]
    return query.strip(), None  # игра не указана — ищем во всех


@router.message(Command("team"))
async def cmd_team(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используй: `/team NaVi` или `/team NaVi dota2`")
        return

    team_name, game = _parse_team_and_game(args[1])

    # Если игра не указана — пробуем обе, берём первый результат
    games_to_try = [game] if game else ["dota2", "cs2"]
    report = None
    for g in games_to_try:
        cached = await cache.get_team_report(team_name, g)
        report = cached if cached else None
        if not report:
            analyzer = Analyzer(db)
            report = await analyzer.team_report(team_name, g)
            if "не найдена" not in report:
                await cache.set_team_report(team_name, g, report)
                break
        else:
            break

    for part in split_message(report or "Команда не найдена."):
        await message.answer(part, reply_markup=back_to_menu())


@router.message(Command("player"))
async def cmd_player(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используй: `/player s1mple` или `/player s1mple dota2`")
        return

    nickname, game = _parse_team_and_game(args[1])

    cached = await cache.get_player_report(nickname, game)
    report = cached if cached else None
    if not report:
        analyzer = Analyzer(db)
        raw_args = args[1].strip().lower().rsplit(maxsplit=1)
        explicit_game = raw_args[-1] in GAME_ALIASES if len(raw_args) > 1 else False
        report = await analyzer.player_report(nickname, game if explicit_game else None)
        await cache.set_player_report(nickname, game, report)

    for part in split_message(report):
        await message.answer(part, reply_markup=back_to_menu())


@router.message(Command("patch"))
async def cmd_patch(message: Message, db: AsyncSession) -> None:
    args = (message.text or "").split(maxsplit=1)
    game_raw = args[1].strip().lower() if len(args) > 1 else "cs2"
    game = GAME_ALIASES.get(game_raw, "cs2")

    cached = await cache.get_patch(game)
    report = cached if cached else None
    if not report:
        analyzer = Analyzer(db)
        report = await analyzer.patch_report(game)
        await cache.set_patch(game, report)

    await message.answer(report, reply_markup=back_to_menu())
