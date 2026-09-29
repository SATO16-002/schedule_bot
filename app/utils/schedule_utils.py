# -*- coding: utf-8 -*-
"""
app/utils/schedule_utils.py — словари дней недели и форматирование расписания.

Единый формат текста используется и в рассылке, и в /today, /tomorrow,
чтобы пользователи видели одно и то же сообщение.
"""
from __future__ import annotations

from app.database.db import Lesson

# Числовые дни недели совпадают с datetime.weekday(): 0 = понедельник ... 6 = воскресенье
DAY_NAMES: dict[int, str] = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

# Все варианты написания дня недели, которые понимает админ в /add_lesson
DAY_ALIASES: dict[str, int] = {}
for _num, _name in DAY_NAMES.items():
    DAY_ALIASES[_name.lower()] = _num
# Короткие названия и частые опечатки/английские сокращения
DAY_ALIASES.update({
    "пн": 0, "пон": 0, "monday": 0, "mon": 0,
    "вт": 1, "втор": 1, "tuesday": 1, "tue": 1,
    "ср": 2, "среда": 2, "wednesday": 2, "wed": 2,
    "чт": 3, "четв": 3, "четверг": 3, "thursday": 3, "thu": 3, "thur": 3,
    "пт": 4, "пят": 4, "friday": 4, "fri": 4,
    "сб": 5, "sub": 5, "saturday": 5, "sat": 5,
    "вс": 6, "воск": 6, "sunday": 6, "sun": 6,
})


def parse_day(raw: str) -> int | None:
    """Превращает 'понедельник' / 'пн' / '0'..'6' в номер дня недели или None."""
    raw = raw.strip().lower().rstrip(".")
    if raw in DAY_ALIASES:
        return DAY_ALIASES[raw]
    if raw.isdigit() and 0 <= int(raw) <= 6:
        return int(raw)
    return None


def format_schedule(day_of_week: int, lessons: list[Lesson]) -> str:
    """Собирает человекочитаемое сообщение-расписание на день."""
    name = DAY_NAMES.get(day_of_week, "День недели")
    if not lessons:
        # Пустое расписание тоже валидный ответ — пишем прямо об этом
        return f"📅 {name}\n\nРасписание пока не заполнено. 🙃"

    lines = [f"📚 <b>Расписание — {name}</b>\n"]
    for ls in lessons:
        lines.append(f"{ls.lesson_number}. {ls.title}")
    return "\n".join(lines)
