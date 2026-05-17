import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from db.database import close_db, init_db, AsyncSessionLocal
from cache.redis_cache import cache
from scheduler.scheduler import create_scheduler
from bot.handlers import router

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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

    # Запускаем планировщик — передаём бота для рассылки уведомлений
    scheduler = create_scheduler(bot=bot)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

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
