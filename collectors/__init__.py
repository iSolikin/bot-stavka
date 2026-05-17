from collectors.opendota import run_opendota_sync
from collectors.hltv import run_hltv_sync
from collectors.liquipedia import run_liquipedia_sync
from collectors.patches import run_patches_sync
from collectors.telegram_collector import run_telegram_sync

__all__ = [
    "run_opendota_sync",
    "run_hltv_sync",
    "run_liquipedia_sync",
    "run_patches_sync",
    "run_telegram_sync",
]
