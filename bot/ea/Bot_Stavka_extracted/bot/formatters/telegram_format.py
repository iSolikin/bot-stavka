"""
Утилиты форматирования для Telegram MarkdownV2.
"""
import re

# Символы, которые нужно экранировать в MarkdownV2
_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_md(text: str) -> str:
    """Экранировать спецсимволы MarkdownV2."""
    # Не трогаем уже экранированные символы
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _MD_SPECIAL:
            # Уже экранировано
            result.append(ch)
            result.append(text[i + 1])
            i += 2
        elif ch in _MD_SPECIAL:
            result.append("\\")
            result.append(ch)
            i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """
    Разбить длинное сообщение на части не более max_length символов.
    Старается разбивать по переносам строк.
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break

        # Ищем последний перенос строки в пределах лимита
        cut = text.rfind("\n", 0, max_length)
        if cut == -1:
            cut = max_length

        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")

    return parts


def bold(text: str) -> str:
    return f"*{escape_md(text)}*"


def code(text: str) -> str:
    return f"`{escape_md(text)}`"


def link(text: str, url: str) -> str:
    return f"[{escape_md(text)}]({url})"
