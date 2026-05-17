from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import User
from config import config
from bot.keyboards import main_menu, back_to_menu
from bot.formatters.telegram_format import escape_md

router = Router()

WELCOME_TEXT = (
    "Привет, *{name}*\\!\n\n"
    "Я *StatLine* — собираю статистику по CS2 и Dota2\\.\n"
    "Только факты: составы, форма, H2H\\. Никаких прогнозов\\.\n\n"
    "Выбери что тебя интересует 👇"
)

HELP_TEXT = (
    "*Как пользоваться ботом:*\n\n"
    "📅 *Матчи* — список игр на ближайшие 48 часов\n\n"
    "🔍 *Поиск команды:*\n"
    "`/team NaVi` — статистика команды \\(CS2\\)\n"
    "`/team NaVi dota2` — статистика команды \\(Dota2\\)\n\n"
    "⚔️ *Сравнение команд:*\n"
    "`/match NaVi vs Vitality` — отчёт по матчу\n\n"
    "👤 *Игрок:*\n"
    "`/player s1mple` — статистика игрока\n\n"
    "🔧 *Патчи:*\n"
    "`/patch cs2` или `/patch dota2`\n\n"
    "🔔 *Уведомления:*\n"
    "`/subscribe NaVi` — уведомление за час до матча \\(CS2\\)\n"
    "`/subscribe OG dota2` — то же для Dota2\n"
    "`/unsubscribe NaVi` — отписаться\n"
    "`/mysubs` — мои подписки"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession) -> None:
    user_id = message.from_user.id

    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            is_admin=user_id in config.ADMIN_IDS,
        )
        db.add(user)
        await db.commit()

    name = escape_md(message.from_user.first_name or "друг")
    await message.answer(
        WELCOME_TEXT.format(name=name),
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=back_to_menu())


# --- Callbacks от кнопок ---

@router.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery) -> None:
    name = escape_md(call.from_user.first_name or "друг")
    await call.message.edit_text(
        WELCOME_TEXT.format(name=name),
        reply_markup=main_menu(),
    )
    await call.answer()


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.edit_text(HELP_TEXT, reply_markup=back_to_menu())
    await call.answer()
