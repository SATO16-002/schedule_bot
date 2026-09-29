# -*- coding: utf-8 -*-
"""
app/handlers/admin.py — команды администратора (доступ только по ADMIN_IDS).

Реализация без FSM: все команды — «одно сообщение = одно действие»,
поэтому достаточно парсинга text.split(maxsplit=N). Это проще и надёжнее,
FSM понадобился бы только для многошаговых диалогов.

Важно: после изменения времени рассылки или целевого чата хендлер сам
пересоздаёт job в планировщике (через app.scheduler.jobs.reschedule_daily_job),
чтобы не ждать перезапуска бота.
"""
from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.config.loader import Config
from app.database import db
from app.handlers.filters import IsAdmin
from app.utils.schedule_utils import DAY_NAMES, parse_day

logger = logging.getLogger(__name__)

# Регулярка для /set_time: "7", "07:30", "7:5"
_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{1,2}))?$")


def _is_int(raw: str) -> bool:
    """Проверяет, что строка — целое число (со знаком)."""
    try:
        int(raw)
        return True
    except ValueError:
        return False


def build_admin_router(config: Config) -> Router:
    """Фабрика админского роутера: замыкает на себе Config.

    Все хендлеры регистрируются внутри, фильтр IsAdmin получает конкретный
    список admin_ids, а тексты ошибок содержат корректные примеры.
    """
    r = Router(name="admin")
    is_admin = IsAdmin(config=config)

    @r.message(is_admin, Command("set_time"))
    async def cmd_set_time(message: Message, command: CommandObject) -> None:
        """Меняет время ежедневной рассылки и переставляет job в планировщике."""
        arg = (command.args or "").strip()
        m = _TIME_RE.match(arg)
        if not m:
            await message.answer(
                "❌ Неверный формат. Пример: <code>/set_time 7:30</code> "
                "или <code>/set_time 6</code>"
            )
            return
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)  # минуты не указаны -> :00
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await message.answer("❌ Часы 0–23, минуты 0–59.")
            return

        await db.set_send_time(hour, minute)

        # Пересоздаём задачу планировщика, чтобы новый час вступил сразу
        from app.scheduler.jobs import reschedule_daily_job
        reschedule_daily_job()

        await message.answer(
            f"✅ Время рассылки обновлено: <b>{hour:02d}:{minute:02d}</b> "
            f"(часовой пояс из настроек)."
        )

    # -----------------------------------------------------------------------
    # /set_chat [chat_id] [topic_id]
    # -----------------------------------------------------------------------
    @r.message(is_admin, Command("set_chat"))
    async def cmd_set_chat(message: Message, command: CommandObject) -> None:
        """Указывает целевой чат и тему форума для рассылки.

        Хитрость UX: если админ вызывает команду ИЗ нужного чата/темы без
        аргументов, берём chat_id и topic_id прямо из входящего сообщения.
        """
        parts = (command.args or "").split()
        if len(parts) >= 2 and _is_int(parts[0]) and _is_int(parts[1]):
            chat_id, topic_id = int(parts[0]), int(parts[1])
        elif len(parts) == 1 and _is_int(parts[0]):
            chat_id, topic_id = int(parts[0]), None
        elif not parts:
            # Авто-режим: текущий чат (и тема, если это форум)
            chat_id = message.chat.id
            topic_id = message.message_thread_id
        else:
            await message.answer(
                "❌ Формат: <code>/set_chat -1001234567890 42</code> "
                "(чат и тема) или <code>/set_chat</code> прямо из нужного чата."
            )
            return

        await db.set_target_chat(chat_id, topic_id)
        await message.answer(
            f"✅ Цель рассылки: чат <code>{chat_id}</code>, "
            f"тема <code>{topic_id if topic_id else '—'}</code>."
        )

    # -----------------------------------------------------------------------
    # /add_lesson [день_недели] [номер_урока] [название...]
    # -----------------------------------------------------------------------
    @r.message(is_admin, Command("add_lesson"))
    async def cmd_add_lesson(message: Message, command: CommandObject) -> None:
        """Добавляет урок или перезаписывает его название (UPSERT по день+номер)."""
        # maxsplit=2: название может содержать пробелы ("Английский язык")
        parts = (command.args or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "❌ Формат: <code>/add_lesson понедельник 3 Алгебра</code>\n"
                "День: полный/короткий (пн, вт...)/число 0–6; номер ≥ 1."
            )
            return

        day = parse_day(parts[0])
        if day is None:
            await message.answer(
                f"❌ Не понял день недели «{parts[0]}». "
                f"Допустимо: {', '.join(DAY_NAMES.values())} или пн…вс."
            )
            return

        if not parts[1].isdigit() or int(parts[1]) < 1:
            await message.answer("❌ Номер урока должен быть целым числом ≥ 1.")
            return
        number = int(parts[1])

        title = parts[2].strip()
        if not title:
            await message.answer("❌ Название урока пустое.")
            return

        existed = any(
            ls.lesson_number == number for ls in await db.get_lessons(day)
        )
        await db.upsert_lesson(day, number, title)
        verb = "обновлён" if existed else "добавлен"
        await message.answer(
            f"✅ Урок {verb}: <b>{DAY_NAMES[day]}</b>, №{number} — «{title}»."
        )

    # -----------------------------------------------------------------------
    # /del_lesson [день_недели] [номер]  (бонус-команда)
    # -----------------------------------------------------------------------
    @r.message(is_admin, Command("del_lesson"))
    async def cmd_del_lesson(message: Message, command: CommandObject) -> None:
        """Удаляет урок."""
        parts = (command.args or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("❌ Формат: <code>/del_lesson пн 3</code>")
            return
        day = parse_day(parts[0])
        if day is None:
            await message.answer("❌ Не понял день недели.")
            return
        removed = await db.delete_lesson(day, int(parts[1]))
        await message.answer(
            "🗑 Удалено." if removed else "❌ Такой урок не найден."
        )

    # -----------------------------------------------------------------------
    # /show_settings — сводка: время, чат, last_sent_date, всё расписание
    # -----------------------------------------------------------------------
    @r.message(is_admin, Command("show_settings"))
    async def cmd_show_settings(message: Message) -> None:
        """Показывает текущие настройки и полное расписание на неделю."""
        s = await db.get_settings()
        head = (
            "⚙️ <b>Настройки бота</b>\n\n"
            f"🕐 Рассылка: <b>{s.send_hour:02d}:{s.send_minute:02d}</b>\n"
            f"🌍 Часовой пояс: <code>{s.timezone}</code>\n"
            f"💬 Чат: <code>{s.chat_id if s.chat_id else 'не задан (/set_chat)'}</code>\n"
            f"📌 Тема: <code>{s.topic_id if s.topic_id else '—'}</code>\n"
            f"🗓 Последняя рассылка: <code>{s.last_sent_date or 'ещё не было'}</code>\n"
        )

        blocks = [head, "\n<b>Расписание:</b>"]
        for dow in range(7):
            lessons = await db.get_lessons(dow)
            if lessons:
                items = ", ".join(f"{ls.lesson_number}. {ls.title}" for ls in lessons)
                blocks.append(f"\n<b>{DAY_NAMES[dow]}:</b> {items}")
            else:
                blocks.append(f"\n<i>{DAY_NAMES[dow]}: пусто</i>")

        text = "".join(blocks)
        # Telegram лимит — 4096 символов; на всякий случай режем с пометкой
        if len(text) > 4096:
            text = text[:4000] + "\n…(слишком длинно, обрезано)"
        await message.answer(text)

    # -----------------------------------------------------------------------
    # /send_now — ручная (тестовая) рассылка
    # -----------------------------------------------------------------------
    @r.message(is_admin, Command("send_now"))
    async def cmd_send_now(message: Message) -> None:
        """Принудительно отправляет сегодняшнее расписание в целевой чат.

        Флаг last_sent_date НЕ трогает — это отладочная команда,
        утренняя автоматическая рассылка должна остаться возможной.
        """
        from app.scheduler.jobs import send_schedule_now
        ok, info = await send_schedule_now(force=True)
        await message.answer(
            f"{'✅' if ok else '⚠️'} {info}"
        )

    # -----------------------------------------------------------------------
    # Fallback: не-адмен попытался ввести админскую команду
    # -----------------------------------------------------------------------
    @r.message(
        ~is_admin,
        Command(
            "set_time", "set_chat", "add_lesson",
            "del_lesson", "show_settings", "send_now",
        ),
    )
    async def cmd_access_denied(message: Message) -> None:
        """Вежливый отказ обычным пользователям."""
        await message.answer("⛔ Эта команда доступна только администраторам.")

    return r


# Модульный роутер по умолчанию — пустой. bot.py всегда использует
# build_admin_router(config), который вернёт заполненный Router.
router = Router(name="admin")
