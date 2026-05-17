from aiogram import Router

from bot.handlers.start import router as start_router
from bot.handlers.matches import router as matches_router
from bot.handlers.teams import router as teams_router
from bot.handlers.subscriptions import router as subscriptions_router
from bot.handlers.admin import router as admin_router
from bot.handlers.bets import router as bets_router
from bot.handlers.today import router as today_router

# Главный роутер — включает все дочерние
router = Router()
router.include_router(start_router)
router.include_router(matches_router)
router.include_router(teams_router)
router.include_router(subscriptions_router)
router.include_router(admin_router)
router.include_router(bets_router)
router.include_router(today_router)

__all__ = ["router"]
