from aiogram import Router

from bot.handlers.start import router as start_router
from bot.handlers.matches import router as matches_router
from bot.handlers.teams import router as teams_router
from bot.handlers.admin import router as admin_router
from bot.handlers.subscriptions import router as subs_router

router = Router()
router.include_router(start_router)
router.include_router(matches_router)
router.include_router(teams_router)
router.include_router(admin_router)
router.include_router(subs_router)

__all__ = ["router"]
