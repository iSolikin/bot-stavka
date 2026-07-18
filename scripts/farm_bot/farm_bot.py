# -*- coding: utf-8 -*-
"""
Farm Bot для Kingdom Realms (North Wilds).

Логика:
  1. Ищет на экране деревья по шаблону templates/tree.png
  2. Кликает по ближайшему к персонажу дереву и добивает его
     (кликает, пока шаблон в этой точке не исчезнет = дерево срублено)
  3. Когда деревьев не осталось — переключается на руду (templates/ore.png)
  4. Когда и руда кончилась — начинает цикл заново (карта могла обновиться)

Управление:
  F8 — пауза / продолжить
  F9 — выход
  Мышь в левый верхний угол экрана — аварийная остановка (failsafe pyautogui)

Перед запуском:
  1. pip install -r requirements.txt
  2. Вырежи шаблоны (Win+Shift+S) и сохрани в папку templates/:
       tree.png — одно дерево (только крона, без фона по краям)
       ore.png  — одна кучка руды
  3. Открой игру, не сворачивай окно, масштаб браузера 100%
  4. python farm_bot.py
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import keyboard
from mss import mss

# ----------------------------- НАСТРОЙКИ -----------------------------------

BASE_DIR = Path(__file__).parent
TEMPLATES = {
    "tree": BASE_DIR / "templates" / "tree.png",
    "ore": BASE_DIR / "templates" / "ore.png",
}

CONFIDENCE = 0.80        # порог совпадения шаблона (0.7–0.9; ниже = больше ложных)
CLICK_INTERVAL = 1.2     # сек между повторными кликами по одной цели
TARGET_TIMEOUT = 45      # сек — максимум на одну цель (если персонаж застрял)
WALK_DELAY = 2.5         # сек ожидания после первого клика (персонаж идёт к цели)
SCAN_DELAY = 1.0         # сек между полными сканами экрана
MONITOR_INDEX = 1        # номер монитора для mss (1 = основной)

# Порядок фарма: сначала все деревья, потом вся руда
FARM_ORDER = ["tree", "ore"]

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


def load_template(path: Path):
    tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if tpl is None:
        print(f"[ERROR] не найден шаблон: {path}")
        print("        Вырежи картинку из игры (Win+Shift+S) и сохрани туда.")
        sys.exit(1)
    return tpl


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


def harvest_target(sct, tpl, pos, name):
    """Кликает по цели, пока она не исчезнет (добыта) или не выйдет таймаут."""
    print(f"  -> добываем {name} в {pos}")
    pyautogui.click(pos[0], pos[1])
    time.sleep(WALK_DELAY)  # персонаж идёт к цели

    deadline = time.time() + TARGET_TIMEOUT
    while _state["running"] and time.time() < deadline:
        wait_if_paused()
        if not target_alive(sct, tpl, pos, (0, 0)):
            print(f"  [OK] {name} добыто")
            return True
        pyautogui.click(pos[0], pos[1])
        time.sleep(CLICK_INTERVAL)

    print(f"  [SKIP] таймаут по цели {name}, идём дальше")
    return False


def farm_resource(sct, name, tpl, screen_center):
    """Добывает все цели одного типа на экране. Возвращает сколько добыто."""
    harvested = 0
    while _state["running"]:
        wait_if_paused()
        screen, offset = grab_screen(sct)
        targets = find_targets(screen, tpl)
        if not targets:
            return harvested

        # экранные координаты + сортировка по близости к центру (там персонаж)
        targets = [(x + offset[0], y + offset[1]) for x, y in targets]
        targets.sort(key=lambda p: (p[0] - screen_center[0]) ** 2
                                   + (p[1] - screen_center[1]) ** 2)

        harvest_target(sct, tpl, targets[0], name)
        harvested += 1
        time.sleep(SCAN_DELAY)
    return harvested


def main():
    templates = {name: load_template(path) for name, path in TEMPLATES.items()}

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

    with mss() as sct:
        while _state["running"]:
            total = 0
            for name in FARM_ORDER:
                wait_if_paused()
                count = farm_resource(sct, name, templates[name], screen_center)
                if count:
                    print(f"[CYCLE] {name}: добыто {count}")
                total += count

            if total == 0:
                print("[IDLE] целей не видно, ждём 10 сек и сканируем снова...")
                time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except pyautogui.FailSafeException:
        print("[FAILSAFE] мышь в углу экрана — бот остановлен.")
    except KeyboardInterrupt:
        print("Остановлено (Ctrl+C).")
