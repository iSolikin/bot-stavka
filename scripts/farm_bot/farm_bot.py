# -*- coding: utf-8 -*-
"""
Farm Bot для Kingdom Realms (North Wilds).

Логика (каждый цикл сканирует экран заново):
  1. Лут на земле (связки брёвен wood_drop.png, куски руды ore_drop.png) —
     подбирается сразу, как только появился
  2. Добыча с чередованием: срубил дерево (tree.png) -> идёт за рудой
     (ore.png) -> снова дерево -> снова руда...
     Если нужного ресурса на экране нет — берёт другой.
  3. Если целей нет — ждёт 10 сек и сканирует снова

Управление:
  F8 — пауза / продолжить
  F9 — выход
  Мышь в левый верхний угол экрана — аварийная остановка (failsafe pyautogui)

Перед запуском:
  1. pip install -r requirements.txt
  2. Вырежи шаблоны (Win+Shift+S) и сохрани в папку templates/:
       tree.png      — одно дерево (только крона, без фона по краям)
       ore.png       — одна кучка руды
       wood_drop.png — связка брёвен, лежащая на земле (лут)
       ore_drop.png  — кусок руды на земле (лут)
  3. Открой игру, не сворачивай окно, масштаб браузера 100%
  4. python farm_bot.py
"""

import sys
import time
from pathlib import Path

# чтобы русский текст не превращался в кракозябры в консоли Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
import pyautogui
import keyboard
from mss import mss

# ----------------------------- НАСТРОЙКИ -----------------------------------

BASE_DIR = Path(__file__).parent
TEMPLATES = {
    "wood_drop": BASE_DIR / "templates" / "wood_drop.png",  # связка брёвен (лут)
    "ore_drop": BASE_DIR / "templates" / "ore_drop.png",    # кусок руды (лут)
    "tree": BASE_DIR / "templates" / "tree.png",             # дерево
    "ore": BASE_DIR / "templates" / "ore.png",               # кучка руды
}

# Лут — это подбор одним кликом, а не добыча
LOOT_TYPES = {"wood_drop", "ore_drop"}

CONFIDENCE = 0.80        # порог совпадения шаблона (0.7–0.9; ниже = больше ложных)
CLICK_INTERVAL = 1.2     # сек между повторными кликами по одной цели
TARGET_TIMEOUT = 45      # сек — максимум на одну цель (если персонаж застрял)
WALK_DELAY = 2.5         # сек ожидания после первого клика (персонаж идёт к цели)
SCAN_DELAY = 1.0         # сек между полными сканами экрана
MONITOR_INDEX = 1        # номер монитора для mss (1 = основной)

# Лут всегда подбираем первым делом
LOOT_ORDER = ["wood_drop", "ore_drop"]
# Добычу чередуем: дерево -> руда -> дерево -> руда ...
HARVEST_ROTATION = ["tree", "ore"]
FARM_ORDER = LOOT_ORDER + HARVEST_ROTATION  # (для статистики)

LOOT_TIMEOUT = 15        # сек — максимум на подбор одного лута

# Голубая шкала прогресса над целью = добыча реально идёт.
# Если после клика шкала так и не появилась — ресурс не бьётся, пропускаем.
BAR_HSV_LO = (90, 130, 170)   # HSV-диапазон цвета шкалы (голубой, hue~94)
BAR_HSV_HI = (99, 190, 255)
BAR_MIN_PIXELS = 25           # столько голубых пикселей = «шкала видна»
NO_BAR_TIMEOUT = 6            # сек: бьём, а шкалы нет -> бросаем цель
BLACKLIST_TTL = 90            # сек: сколько помним небьющиеся цели
BLACKLIST_RADIUS = 60         # px: радиус «это та же мёртвая цель»

PAUSE_KEY = "f8"
EXIT_KEY = "f9"

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# ----------------------------------------------------------------------------

_state = {"paused": False, "running": True}


def _toggle_pause():
    _state["paused"] = not _state["paused"]
    print(("[PAUSE] пауза" if _state["paused"] else "[PAUSE] продолжаем"))


def _stop():
    _state["running"] = False
    print("[EXIT] выходим...")


def wait_if_paused():
    while _state["paused"] and _state["running"]:
        time.sleep(0.2)
    if not _state["running"]:
        sys.exit(0)


def grab_screen(sct):
    """Скриншот монитора -> BGR numpy array + смещение монитора."""
    mon = sct.monitors[MONITOR_INDEX]
    img = np.array(sct.grab(mon))          # BGRA
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), (mon["left"], mon["top"])


def load_templates():
    """Загружает шаблоны. Работает и с одним из двух, если второго нет."""
    templates = {}
    for name, path in TEMPLATES.items():
        tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[WARNING] нет шаблона {path.name} — '{name}' фармить не буду.")
        else:
            templates[name] = tpl

    if not templates:
        print()
        print("[ERROR] Нет ни одного шаблона! Боту не с чем сравнивать экран.")
        print("Что сделать:")
        print("  1. Открой игру, нажми Win+Shift+S")
        print("  2. Выдели рамкой ОДНО дерево (только крону, без лишнего фона)")
        print("  3. Вставь в Paint (Ctrl+V) и сохрани как:")
        print(f"       {TEMPLATES['tree']}")
        print("  4. То же самое с кучкой руды:")
        print(f"       {TEMPLATES['ore']}")
        sys.exit(1)
    return templates


def find_targets(screen, tpl, threshold=CONFIDENCE):
    """Все совпадения шаблона на экране -> список центров (x, y), лучшие первыми."""
    h, w = tpl.shape[:2]
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    candidates = sorted(zip(xs, ys), key=lambda p: res[p[1], p[0]], reverse=True)

    centers = []
    for x, y in candidates:
        cx, cy = x + w // 2, y + h // 2
        # простая NMS: пропускаем точки рядом с уже найденными
        if all(abs(cx - px) > w * 0.6 or abs(cy - py) > h * 0.6 for px, py in centers):
            centers.append((cx, cy))
    return centers


def target_alive(sct, tpl, pos, offset, threshold=CONFIDENCE):
    """Есть ли ещё цель в окрестности точки pos (в экранных координатах)."""
    screen, off = grab_screen(sct)
    h, w = tpl.shape[:2]
    x = pos[0] - off[0]
    y = pos[1] - off[1]
    x0, y0 = max(0, x - w), max(0, y - h)
    x1 = min(screen.shape[1], x + w)
    y1 = min(screen.shape[0], y + h)
    region = screen[y0:y1, x0:x1]
    if region.shape[0] < h or region.shape[1] < w:
        return False
    res = cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED)
    return res.max() >= threshold


def bar_visible(sct, pos):
    """Видна ли голубая шкала прогресса в области над целью pos."""
    screen, off = grab_screen(sct)
    x, y = pos[0] - off[0], pos[1] - off[1]
    x0, y0 = max(0, x - 90), max(0, y - 150)
    x1, y1 = min(screen.shape[1], x + 90), max(1, y - 10)
    roi = screen[y0:y1, x0:x1]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(BAR_HSV_LO), np.array(BAR_HSV_HI))
    return int(cv2.countNonZero(mask)) >= BAR_MIN_PIXELS


def harvest_target(sct, tpl, pos, name, blacklist):
    """Кликает по цели, пока она не исчезнет (добыта/подобрана) или таймаут.

    Для дерева/руды следит за голубой шкалой прогресса: если после кликов
    шкала не появилась за NO_BAR_TIMEOUT сек — ресурс не бьётся, заносим
    его в чёрный список и идём к следующему.
    """
    is_loot = name in LOOT_TYPES
    action = "подбираем" if is_loot else "добываем"
    print(f"  -> {action} {name} в {pos}")
    pyautogui.click(pos[0], pos[1])
    time.sleep(WALK_DELAY)  # персонаж идёт к цели

    start = time.time()
    deadline = start + (LOOT_TIMEOUT if is_loot else TARGET_TIMEOUT)
    bar_seen = False
    last_bar = 0.0
    last_click = start

    while _state["running"] and time.time() < deadline:
        wait_if_paused()
        if not target_alive(sct, tpl, pos, (0, 0)):
            print(f"  [OK] {name} {'подобрано' if is_loot else 'добыто'}")
            return True

        if not is_loot:
            now = time.time()
            if bar_visible(sct, pos):
                bar_seen = True
                last_bar = now
            elif not bar_seen:
                if now - start > NO_BAR_TIMEOUT:
                    print(f"  [DEAD] {name} в {pos}: шкалы нет — не бьётся, "
                          f"пропускаем")
                    blacklist.append((pos, now))
                    return False
                if now - last_click >= CLICK_INTERVAL:
                    pyautogui.click(pos[0], pos[1])
                    last_click = now
            elif now - last_bar > 4:
                # шкала была, но пропала, а цель жива — толкнём ещё раз
                pyautogui.click(pos[0], pos[1])
                last_click = now
                bar_seen = False

        time.sleep(0.5)

    print(f"  [SKIP] таймаут по цели {name}, идём дальше")
    blacklist.append((pos, time.time()))
    return False


def pick_next_target(sct, templates, screen_center, preferred, blacklist):
    """Сканирует экран, возвращает (тип, позиция) следующей цели.

    Порядок: сначала лут с земли, потом добыча с чередованием — если в
    прошлый раз рубили дерево, теперь ищем руду (и наоборот). Если
    предпочтительного ресурса на экране нет — берём другой.
    Среди целей одного типа берём ближайшую к персонажу (центру экрана).
    Цели из чёрного списка (небьющиеся) пропускаются.
    """
    now = time.time()
    blacklist[:] = [(p, t) for p, t in blacklist if now - t < BLACKLIST_TTL]

    def is_dead(pos):
        return any((pos[0] - p[0]) ** 2 + (pos[1] - p[1]) ** 2
                   < BLACKLIST_RADIUS ** 2 for p, _ in blacklist)

    rotation = [preferred] + [n for n in HARVEST_ROTATION if n != preferred]
    screen, offset = grab_screen(sct)
    for name in LOOT_ORDER + rotation:
        if name not in templates:
            continue
        targets = find_targets(screen, templates[name])
        targets = [(x + offset[0], y + offset[1]) for x, y in targets]
        targets = [p for p in targets if not is_dead(p)]
        if not targets:
            continue
        targets.sort(key=lambda p: (p[0] - screen_center[0]) ** 2
                                   + (p[1] - screen_center[1]) ** 2)
        return name, targets[0]
    return None, None


def main():
    templates = load_templates()

    keyboard.add_hotkey(PAUSE_KEY, _toggle_pause)
    keyboard.add_hotkey(EXIT_KEY, _stop)

    sw, sh = pyautogui.size()
    screen_center = (sw // 2, sh // 2)

    print("=" * 55)
    print(" Farm Bot: деревья -> руда")
    print(f" {PAUSE_KEY.upper()} — пауза | {EXIT_KEY.upper()} — выход | "
          f"мышь в левый верхний угол — аварийный стоп")
    print("=" * 55)
    print("Старт через 5 секунд — переключись на окно игры!")
    time.sleep(5)

    stats = {name: 0 for name in FARM_ORDER}
    preferred = HARVEST_ROTATION[0]  # с чего начинаем добычу
    blacklist = []                   # небьющиеся цели: [(pos, время)]
    with mss() as sct:
        while _state["running"]:
            wait_if_paused()
            name, pos = pick_next_target(sct, templates, screen_center,
                                         preferred, blacklist)
            if name is None:
                print("[IDLE] целей не видно, ждём 10 сек и сканируем снова...")
                time.sleep(10)
                continue

            if harvest_target(sct, templates[name], pos, name, blacklist):
                stats[name] += 1
                print("[STATS] " + " | ".join(
                    f"{k}: {v}" for k, v in stats.items() if v))

            if name in HARVEST_ROTATION:
                # чередование: после дерева идём за рудой и наоборот
                idx = HARVEST_ROTATION.index(name)
                preferred = HARVEST_ROTATION[(idx + 1) % len(HARVEST_ROTATION)]
            time.sleep(SCAN_DELAY)


if __name__ == "__main__":
    try:
        main()
    except pyautogui.FailSafeException:
        print("[FAILSAFE] мышь в углу экрана — бот остановлен.")
    except KeyboardInterrupt:
        print("Остановлено (Ctrl+C).")
