import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from db.database import close_db, init_db, AsyncSessionLocal
from cache.redis_cache import cache
from scheduler.scheduler import create_scheduler
from bot.handlers import router

# Настройка логирования — только в файл, без StreamHandler (нет консоли при скрытом запуске)
_log_file = os.path.join(os.path.dirname(__file__), "bot_err.log")
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Starting esports bot...")

    # Инициализация БД
    await init_db()

    # Подключение Redis
    try:
        await cache.connect()
    except Exception as e:
        logger.warning("Redis not available: %s — cache disabled", e)

    # Создаём бота и диспетчер
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware: прокидываем сессию БД в хендлеры
    from aiogram import BaseMiddleware
    from typing import Callable, Awaitable, Any
    from aiogram.types import TelegramObject

    class DbSessionMiddleware(BaseMiddleware):
        async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: dict[str, Any],
        ) -> Any:
            async with AsyncSessionLocal() as session:
                data["db"] = session
                return await handler(event, data)

    dp.update.middleware(DbSessionMiddleware())

    # Подключаем роутеры
    dp.include_router(router)

    # Запускаем планировщик (передаём бота для уведомлений)
    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    # Первоначальная загрузка истории матчей в фоне (не блокирует старт)
    async def _startup_history_sync() -> None:
        await asyncio.sleep(15)  # ждём 15 сек пока бот поднимется
        try:
            logger.info("Startup: running OpenDota history sync...")
            from collectors.opendota import run_opendota_history_sync
            async with AsyncSessionLocal() as db:
                await run_opendota_history_sync(db)
            logger.info("Startup: OpenDota history sync done")
        except Exception as exc:
            logger.error("Startup history sync failed: %s", exc, exc_info=True)

    # Анализ всех матчей дня сразу после загрузки истории
    async def _startup_daily_analysis() -> None:
        await asyncio.sleep(90)  # ждём после history sync (~60-80 сек)
        try:
            logger.info("Startup: running daily analysis...")
            from analyzer.daily_analysis import analyze_all_today
            async with AsyncSessionLocal() as db:
                results = await analyze_all_today(db)
            new_bets = sum(1 for r in results if r.get("bet_placed"))
            logger.info(
                "Startup: daily analysis done — %d matches, %d bets placed",
                len(results), new_bets,
            )
        except Exception as exc:
            logger.error("Startup daily analysis failed: %s", exc, exc_info=True)

    asyncio.create_task(_startup_history_sync())
    asyncio.create_task(_startup_daily_analysis())

    logger.info("Bot started. Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await cache.close()
        await close_db()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
