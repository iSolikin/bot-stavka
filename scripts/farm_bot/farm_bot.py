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

import logging
import sys
import time
from pathlib import Path

# чтобы русский текст не превращался в кракозябры в консоли Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
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
TARGET_TIMEOUT = 45      # сек БЕЗ ПРОГРЕССА на одну цель; пока шкала видна
                         # (рубка идёт) — таймаут продлевается
TARGET_HARD_CAP = 180    # сек — жёсткий потолок на одну цель

# ВАЖНО: лишние клики сбивают добычу! Один клик — персонаж сам идёт и сам
# добывает до конца. Второй клик разрешён только если персонаж пришёл,
# стоит, а добыча так и не началась.
MAX_CLICKS_PER_TARGET = 2
RECLICK_COOLDOWN = 5     # сек после клика, раньше которых второй не даём
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
BLACKLIST_TTL = 90            # сек: чёрный список после застревания/таймаута
BLACKLIST_DEAD_TTL = 600      # сек: список для «не бьётся» (нужен уровень выше)
BLACKLIST_RADIUS = 60         # px: радиус «это та же мёртвая цель»

# Ресурс не того уровня выглядит иначе по цвету (серый камень vs тёмная
# руда) — совпадение по форме отсекаем сверкой среднего цвета с шаблоном.
COLOR_TOLERANCE = 28          # макс. расхождение среднего цвета (по каналу)

# Детект застревания: если персонаж стоит на месте (карта не двигается),
# добычи нет и так продолжается STUCK_TIMEOUT сек — бросаем цель и рубим
# ближайший ресурс (скорее всего именно он перегородил дорогу).
STUCK_TIMEOUT = 15            # сек без движения = застрял
MOVE_DIFF_THRESHOLD = 1.5     # средняя разница кадров, выше = «карта едет»

# Серверный рассинхрон: шкала видна, но не двигается. Единичный случай —
# бросаем цель; несколько подряд — обновляем страницу (F5 лечит рассинхрон,
# игра загружается обратно прямо в зону фарма).
FROZEN_BAR_TIMEOUT = 20       # сек: заполнение шкалы не меняется = зависло
BAR_PIXEL_TOLERANCE = 5       # на сколько пикселей должно меняться заполнение
FROZEN_STREAK_RELOAD = 2      # столько FROZEN подряд = жмём F5
RELOAD_WAIT = 15              # сек ждать перезагрузку страницы

# Если F5 не помог (снова серия FROZEN без единой добычи) — делаем полный
# перезаход в зону: Return to Kingdom -> Raids -> Adventure Outpost.
# Это лечит застрявшего персонажа (баг игры «застрял в дереве/камне»).
RETURN_BTN = (1827, 996)      # кнопка Return to Kingdom (низ-право зоны)
RAIDS_BTN = (1688, 982)       # иконка Raids на нижней панели королевства
CLAIM_BTN = (959, 817)        # Claim All Items в окне «While You Were Away»
OUTPOST_FALLBACK = (1050, 575)  # запасная точка клика по аванпосту
OUTPOST_TEMPLATE = BASE_DIR / "templates" / "outpost.png"

# Бот кликает только когда окно игры в фокусе. Если фокус ушёл (свернул,
# переключился) — ждём WINDOW_GRACE сек и сами возвращаем окно наверх.
GAME_WINDOW_TITLE = "Kingdom Realms"
WINDOW_GRACE = 45             # сек ждать, пока юзер сам вернётся в игру

# Если целей на экране нет (всё вырублено или в чёрном списке) — не стоим
# на месте, а идём разведывать карту по кругу направлений.
EXPLORE_POINTS = [(1500, 350), (450, 300), (700, 860), (1550, 800)]
IDLE_SCANS_BEFORE_EXPLORE = 2  # сколько пустых сканов терпим перед разведкой

PAUSE_KEY = "f8"
EXIT_KEY = "f9"

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# ----------------------------- ЛОГИ ----------------------------------------
# Пишем и в консоль, и в файл logs/farm_ГГГГММДД_ЧЧММСС.log (UTF-8).

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
log = logging.getLogger("farm_bot")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
_file_handler = logging.FileHandler(
    LOG_DIR / time.strftime("farm_%Y%m%d_%H%M%S.log"), encoding="utf-8")
_file_handler.setFormatter(_fmt)
log.addHandler(_file_handler)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
log.addHandler(_console_handler)

# ----------------------------------------------------------------------------

_state = {"paused": False, "running": True}


def _toggle_pause():
    _state["paused"] = not _state["paused"]
    log.info(("[PAUSE] пауза" if _state["paused"] else "[PAUSE] продолжаем"))


def _stop():
    _state["running"] = False
    log.info("[EXIT] выходим...")


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
            log.info(f"[WARNING] нет шаблона {path.name} — '{name}' фармить не буду.")
        else:
            templates[name] = tpl

    if not templates:
        log.info("[ERROR] Нет ни одного шаблона! Боту не с чем сравнивать экран.")
        log.info("Что сделать:")
        log.info("  1. Открой игру, нажми Win+Shift+S")
        log.info("  2. Выдели рамкой ОДНО дерево (только крону, без лишнего фона)")
        log.info("  3. Вставь в Paint (Ctrl+V) и сохрани как:")
        log.info(f"       {TEMPLATES['tree']}")
        log.info("  4. То же самое с кучкой руды:")
        log.info(f"       {TEMPLATES['ore']}")
        sys.exit(1)
    return templates


def find_targets(screen, tpl, threshold=CONFIDENCE):
    """Все совпадения шаблона на экране -> список центров (x, y), лучшие первыми.

    Совпадения, похожие по форме, но другого цвета (например, камень
    старшего уровня — серый вместо тёмного), отбрасываются по среднему цвету.
    """
    h, w = tpl.shape[:2]
    tpl_mean = tpl.reshape(-1, 3).mean(axis=0)
    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    candidates = sorted(zip(xs, ys), key=lambda p: res[p[1], p[0]], reverse=True)

    centers = []
    for x, y in candidates:
        cx, cy = x + w // 2, y + h // 2
        # простая NMS: пропускаем точки рядом с уже найденными
        if any(abs(cx - px) <= w * 0.6 and abs(cy - py) <= h * 0.6
               for px, py in centers):
            continue
        # сверка цвета: не тот оттенок = не тот ресурс, пропускаем
        region_mean = screen[y:y + h, x:x + w].reshape(-1, 3).mean(axis=0)
        if np.abs(region_mean - tpl_mean).max() > COLOR_TOLERANCE:
            continue
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


def game_window_active():
    """Игра сейчас на переднем плане? Кликаем только когда да."""
    try:
        w = gw.getActiveWindow()
        return w is not None and GAME_WINDOW_TITLE in w.title
    except Exception:
        return True  # не смогли проверить — не блокируем работу


def focus_game_window():
    """Возвращает окно игры на передний план (несколько способов)."""
    wins = [w for w in gw.getAllWindows() if GAME_WINDOW_TITLE in w.title]
    if not wins:
        log.info(f"[FOCUS] окно '{GAME_WINDOW_TITLE}' не найдено — игра закрыта?")
        return False
    w = wins[0]

    # способ 1: SetForegroundWindow (нажатый Alt снимает блокировку Windows)
    try:
        pyautogui.press("altleft")
        w.activate()
        time.sleep(1.5)
    except Exception:
        pass
    if game_window_active():
        return True

    # способ 2: свернуть/развернуть
    try:
        w.minimize()
        time.sleep(0.5)
        w.restore()
        time.sleep(1.5)
    except Exception:
        pass
    if game_window_active():
        return True

    # способ 3: клик внутрь окна игры (правее центра, вне игровых кнопок)
    try:
        pyautogui.click(w.right - 250, w.top + 350)
        time.sleep(1.5)
    except Exception:
        pass
    return game_window_active()


def reload_game():
    """Обновляет страницу игры (F5) — лечит серверный рассинхрон.

    Игра после перезагрузки попадает обратно прямо в зону фарма.
    Чёрный список НЕ чистим: если эти цели были битые, пусть остаются
    в игноре — бот попробует другие.
    """
    log.info("[RELOAD] похоже на рассинхрон сервера — обновляю страницу (F5)")
    if not game_window_active():
        focus_game_window()
    pyautogui.press("f5")
    time.sleep(RELOAD_WAIT)


def reenter_zone(sct, blacklist):
    """Полный перезаход: Return to Kingdom -> Raids -> Adventure Outpost.

    Лечит игровой баг «персонаж застрял в дереве/камне», который не
    лечится обновлением страницы (позиция хранится на сервере, но
    перезаход её сбрасывает). Проверено вручную.
    """
    log.info("[REENTER] F5 не помогает — перезахожу в зону через королевство")
    if not game_window_active():
        focus_game_window()

    pyautogui.click(RETURN_BTN[0], RETURN_BTN[1])
    time.sleep(6)

    # окно «While You Were Away» появляется не всегда — ищем оранжевую
    # кнопку Claim All Items по цвету и жмём, если она есть
    screen, _ = grab_screen(sct)
    btn = screen[805:830, 870:1050].reshape(-1, 3).mean(axis=0)  # BGR
    if btn[2] > 130 and btn[0] < 90:
        log.info("[REENTER] забираю накопленные ресурсы (Claim All Items)")
        pyautogui.click(CLAIM_BTN[0], CLAIM_BTN[1])
        time.sleep(2.5)

    pyautogui.click(RAIDS_BTN[0], RAIDS_BTN[1])
    time.sleep(4)

    # Adventure Outpost ищем по шаблону, фиксированная точка — запасной путь
    clicked = False
    outpost = cv2.imread(str(OUTPOST_TEMPLATE))
    if outpost is not None:
        screen, off = grab_screen(sct)
        res = cv2.matchTemplate(screen, outpost, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx >= 0.70:
            h, w = outpost.shape[:2]
            pyautogui.click(loc[0] + w // 2 + off[0],
                            loc[1] + h // 2 + off[1])
            clicked = True
        else:
            log.info(f"[REENTER] аванпост не найден по шаблону "
                     f"(match={mx:.2f}), кликаю по запасной точке")
    if not clicked:
        pyautogui.click(OUTPOST_FALLBACK[0], OUTPOST_FALLBACK[1])
    time.sleep(8)
    blacklist.clear()  # после перезахода цели снова рабочие


def motion_frame(sct, screen_center):
    """Мини-кадр вокруг персонажа для детекта движения камеры.

    Сам персонаж в центре вырезается (его анимация не считается движением):
    когда персонаж идёт, камера едет за ним и меняется ВСЯ картинка вокруг.
    """
    screen, off = grab_screen(sct)
    cx, cy = screen_center[0] - off[0], screen_center[1] - off[1]
    x0, y0 = max(0, cx - 350), max(0, cy - 250)
    x1 = min(screen.shape[1], cx + 350)
    y1 = min(screen.shape[0], cy + 250)
    roi = cv2.cvtColor(screen[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    h, w = roi.shape
    roi[max(0, h // 2 - 120):h // 2 + 120,
        max(0, w // 2 - 120):w // 2 + 120] = 0
    return cv2.resize(roi, (w // 4, h // 4)).astype(np.int16)


def wait_camera_still(sct, screen_center, timeout=15):
    """Ждёт, пока камера остановится (персонаж дошёл до места).

    Нужно после [MOVED]: если сканировать на ходу, ближайшая цель
    меняется каждую секунду и персонаж мечется между целями.
    """
    prev = motion_frame(sct, screen_center)
    still_since = None
    end = time.time() + timeout
    while _state["running"] and time.time() < end:
        time.sleep(0.4)
        cur = motion_frame(sct, screen_center)
        moving = (cur.shape != prev.shape
                  or np.abs(cur - prev).mean() > MOVE_DIFF_THRESHOLD)
        prev = cur
        if moving:
            still_since = None
        elif still_since is None:
            still_since = time.time()
        elif time.time() - still_since >= 1.2:
            return True
    return False


def bar_pixels(sct, pos):
    """Сколько пикселей голубой шкалы видно над целью pos.

    0 или мало = шкалы нет; заполнение шкалы меняется по мере добычи,
    поэтому по этому же числу ловим «замёрзшую» шкалу (рассинхрон).
    """
    screen, off = grab_screen(sct)
    x, y = pos[0] - off[0], pos[1] - off[1]
    # узкая зона: чтобы не цеплять шкалы соседних ресурсов и чужих игроков
    x0, y0 = max(0, x - 70), max(0, y - 150)
    x1, y1 = min(screen.shape[1], x + 70), max(1, y - 10)
    roi = screen[y0:y1, x0:x1]
    if roi.size == 0:
        return 0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(BAR_HSV_LO), np.array(BAR_HSV_HI))
    return int(cv2.countNonZero(mask))


def harvest_target(sct, tpl, pos, name, blacklist, screen_center):
    """Один клик по цели — персонаж сам идёт и добывает; мы ждём и следим.

    Максимум MAX_CLICKS_PER_TARGET кликов: постоянное кликанье СБИВАЕТ
    добычу. Второй клик — только если пришли, стоим, а добыча не началась.

    Возвращает статус:
      "ok"    — добыто/подобрано
      "dead"  — шкала прогресса не появилась, ресурс не бьётся
      "stuck" — персонаж застрял на месте (что-то перегородило дорогу)
      "skip"  — общий таймаут

    Для дерева/руды следит за голубой шкалой прогресса: если после кликов
    шкала не появилась за NO_BAR_TIMEOUT сек — ресурс не бьётся, заносим
    его в чёрный список и идём к следующему.
    Если карта не двигается, добычи нет и так STUCK_TIMEOUT сек подряд —
    персонаж застрял: бросаем цель, чтобы срубить то, что мешает.
    """
    is_loot = name in LOOT_TYPES
    action = "подбираем" if is_loot else "добываем"
    log.info(f"  -> {action} {name} в {pos}")
    pyautogui.click(pos[0], pos[1])
    clicks = 1
    bar_seen = False
    last_click = time.time()

    # персонаж идёт к цели; по пути уже поглядываем на шкалу, чтобы не
    # пропустить быструю добычу (мелкие деревья умирают за пару секунд)
    walk_end = time.time() + WALK_DELAY
    while _state["running"] and time.time() < walk_end:
        if not is_loot and bar_pixels(sct, pos) >= BAR_MIN_PIXELS:
            bar_seen = True
        time.sleep(0.4)

    start = time.time()
    deadline = start + (LOOT_TIMEOUT if is_loot else TARGET_TIMEOUT)
    last_bar = 0.0
    last_move = start
    prev_frame = motion_frame(sct, screen_center)
    prev_fill = 0
    fill_changed_at = start
    last_work_log = start

    while _state["running"] and time.time() < deadline:
        wait_if_paused()
        if not game_window_active():
            # окно игры ушло с переднего плана — не кликаем, просто ждём
            time.sleep(2)
            continue

        now = time.time()
        if not target_alive(sct, tpl, pos, (0, 0)):
            # цель пропала с этой точки экрана. Это добыча ТОЛЬКО если
            # камера стояла. Если персонаж шёл — картинка просто уехала
            # вместе с камерой, и «исчезновение» ложное.
            camera_moving = now - last_move < 1.2
            if not camera_moving and (is_loot or bar_seen):
                log.info(f"  [OK] {name} "
                         f"{'подобрано' if is_loot else 'добыто'} "
                         f"(кликов: {clicks})")
                return "ok"
            log.info(f"  [MOVED] {name}: карта сдвинулась — пересканирую")
            return "moved"

        # детект движения камеры (персонаж идёт -> картинка вокруг едет)
        cur_frame = motion_frame(sct, screen_center)
        if cur_frame.shape == prev_frame.shape:
            if np.abs(cur_frame - prev_frame).mean() > MOVE_DIFF_THRESHOLD:
                last_move = now
        else:
            last_move = now
        prev_frame = cur_frame
        standing = now - last_move > 2.5  # персонаж стоит на месте

        harvesting = False
        if not is_loot:
            fill = bar_pixels(sct, pos)
            if fill >= BAR_MIN_PIXELS:
                # добыча идёт — НИКАКИХ кликов, просто ждём и следим
                bar_seen = True
                last_bar = now
                harvesting = True
                # шкала замёрзла = серверный рассинхрон, цель бесполезна
                if abs(fill - prev_fill) > BAR_PIXEL_TOLERANCE:
                    prev_fill = fill
                    fill_changed_at = now
                elif now - fill_changed_at > FROZEN_BAR_TIMEOUT:
                    log.info(f"  [FROZEN] {name} в {pos}: шкала зависла "
                          f"(лаг сервера) — бросаем на "
                          f"{BLACKLIST_DEAD_TTL // 60} мин")
                    blacklist.append((pos, now + BLACKLIST_DEAD_TTL))
                    return "frozen"
                # длинная цель: продлеваем таймаут, пока есть прогресс
                deadline = min(start + TARGET_HARD_CAP,
                               max(deadline, now + TARGET_TIMEOUT))
                if now - last_work_log > 30:
                    log.info(f"  [WORK] {name}: добыча идёт "
                             f"({int(now - start)} сек)...")
                    last_work_log = now
            elif standing and now - last_click > RECLICK_COOLDOWN:
                # пришли, стоим, а добыча не началась (или прервалась)
                if clicks < MAX_CLICKS_PER_TARGET:
                    log.info(f"  [CLICK-2] добыча не началась — кликаем ещё раз")
                    pyautogui.click(pos[0], pos[1])
                    clicks += 1
                    last_click = now
                elif now - max(last_bar, start) > NO_BAR_TIMEOUT:
                    log.info(f"  [DEAD] {name} в {pos}: шкалы нет — не бьётся "
                          f"(мал уровень?), пропускаем на "
                          f"{BLACKLIST_DEAD_TTL // 60} мин")
                    blacklist.append((pos, now + BLACKLIST_DEAD_TTL))
                    return "dead"

        if not harvesting and now - last_move > STUCK_TIMEOUT:
            log.info(f"  [STUCK] застряли по пути к {name} в {pos} — "
                  f"переключаемся на ближайший ресурс")
            blacklist.append((pos, now + BLACKLIST_TTL))
            return "stuck"

        time.sleep(0.5)

    log.info(f"  [SKIP] таймаут по цели {name}, идём дальше")
    blacklist.append((pos, time.time() + BLACKLIST_TTL))
    return "skip"


def pick_next_target(sct, templates, screen_center, preferred, blacklist,
                     any_nearest=False):
    """Сканирует экран, возвращает (тип, позиция) следующей цели.

    Порядок: сначала лут с земли, потом добыча с чередованием — если в
    прошлый раз рубили дерево, теперь ищем руду (и наоборот). Если
    предпочтительного ресурса на экране нет — берём другой.
    Среди целей одного типа берём ближайшую к персонажу (центру экрана).
    Цели из чёрного списка (небьющиеся) пропускаются.

    any_nearest=True — режим после застревания: берём ближайшую к персонажу
    цель ЛЮБОГО типа, чтобы срубить то, что перегородило дорогу.
    """
    now = time.time()
    blacklist[:] = [(p, expires) for p, expires in blacklist if now < expires]

    def is_dead(pos):
        return any((pos[0] - p[0]) ** 2 + (pos[1] - p[1]) ** 2
                   < BLACKLIST_RADIUS ** 2 for p, _ in blacklist)

    def dist(p):
        return (p[0] - screen_center[0]) ** 2 + (p[1] - screen_center[1]) ** 2

    screen, offset = grab_screen(sct)

    def found(name):
        targets = find_targets(screen, templates[name])
        targets = [(x + offset[0], y + offset[1]) for x, y in targets]
        return [p for p in targets if not is_dead(p)]

    if any_nearest:
        # режим «расчистить дорогу»: ближайшая цель любого типа
        best = None
        for name in LOOT_ORDER + HARVEST_ROTATION:
            if name not in templates:
                continue
            for p in found(name):
                if best is None or dist(p) < dist(best[1]):
                    best = (name, p)
        if best:
            return best
        return None, None

    rotation = [preferred] + [n for n in HARVEST_ROTATION if n != preferred]
    for name in LOOT_ORDER + rotation:
        if name not in templates:
            continue
        targets = found(name)
        if not targets:
            continue
        targets.sort(key=dist)
        return name, targets[0]
    return None, None


def main():
    templates = load_templates()

    keyboard.add_hotkey(PAUSE_KEY, _toggle_pause)
    keyboard.add_hotkey(EXIT_KEY, _stop)

    sw, sh = pyautogui.size()
    screen_center = (sw // 2, sh // 2)

    log.info("=" * 55)
    log.info(" Farm Bot: деревья -> руда")
    log.info(f" {PAUSE_KEY.upper()} — пауза | {EXIT_KEY.upper()} — выход | "
          f"мышь в левый верхний угол — аварийный стоп")
    log.info("=" * 55)
    log.info("Старт через 5 секунд — поднимаю окно игры...")
    time.sleep(5)
    if not game_window_active():
        focus_game_window()

    stats = {name: 0 for name in FARM_ORDER}
    preferred = HARVEST_ROTATION[0]  # с чего начинаем добычу
    blacklist = []                   # небьющиеся цели: [(pos, время)]
    clear_blocker = False            # после застревания рубим ближайшее
    window_lost_since = None         # с какого момента игра не в фокусе
    frozen_streak = 0                # подряд замёрзших шкал (рассинхрон)
    recoveries = 0                   # восстановлений без единой добычи
    idle_scans = 0                   # подряд пустых сканов
    explore_idx = 0                  # какое направление разведки следующее
    with mss() as sct:
        while _state["running"]:
            wait_if_paused()

            if not game_window_active():
                now = time.time()
                if window_lost_since is None:
                    window_lost_since = now
                    log.info("[WAIT] окно игры не в фокусе — не кликаю, жду...")
                elif now - window_lost_since > WINDOW_GRACE:
                    log.info("[FOCUS] возвращаю окно игры на передний план")
                    focus_game_window()
                    window_lost_since = None
                time.sleep(3)
                continue
            window_lost_since = None

            name, pos = pick_next_target(sct, templates, screen_center,
                                         preferred, blacklist,
                                         any_nearest=clear_blocker)
            if name is None:
                clear_blocker = False
                idle_scans += 1
                if idle_scans >= IDLE_SCANS_BEFORE_EXPLORE:
                    px, py = EXPLORE_POINTS[explore_idx % len(EXPLORE_POINTS)]
                    explore_idx += 1
                    idle_scans = 0
                    log.info(f"[EXPLORE] целей не видно — разведываем "
                             f"карту, идём в ({px}, {py})")
                    pyautogui.click(px, py)
                    wait_camera_still(sct, screen_center)
                else:
                    log.info("[IDLE] целей не видно, ждём 10 сек и "
                             "сканируем снова...")
                    time.sleep(10)
                continue
            idle_scans = 0

            status = harvest_target(sct, templates[name], pos, name,
                                    blacklist, screen_center)
            if status == "ok":
                stats[name] += 1
                frozen_streak = 0
                recoveries = 0
                log.info("[STATS] " + " | ".join(
                    f"{k}: {v}" for k, v in stats.items() if v))
            elif status == "frozen":
                frozen_streak += 1
                if frozen_streak >= FROZEN_STREAK_RELOAD:
                    # эскалация: сначала F5; если после него так и не было
                    # ни одной добычи — полный перезаход в зону
                    if recoveries == 0:
                        reload_game()
                    else:
                        reenter_zone(sct, blacklist)
                    recoveries += 1
                    frozen_streak = 0

            # застряли -> следующей целью берём ближайший ресурс любого
            # типа: скорее всего именно он и перегородил дорогу
            clear_blocker = (status == "stuck")

            if status == "moved":
                # персонаж ещё в пути — ждём, пока он дойдёт (камера
                # встанет), и только потом сканируем: иначе «ближайшая»
                # цель меняется на ходу и персонаж мечется
                wait_camera_still(sct, screen_center)
                continue

            if name in HARVEST_ROTATION:
                # чередование: после дерева идём за рудой и наоборот
                idx = HARVEST_ROTATION.index(name)
                preferred = HARVEST_ROTATION[(idx + 1) % len(HARVEST_ROTATION)]
            time.sleep(SCAN_DELAY)


if __name__ == "__main__":
    try:
        main()
    except pyautogui.FailSafeException:
        log.info("[FAILSAFE] мышь в углу экрана — бот остановлен.")
    except KeyboardInterrupt:
        log.info("Остановлено (Ctrl+C).")
    except SystemExit:
        pass
    except Exception:
        log.exception("[CRASH] бот упал с ошибкой:")
