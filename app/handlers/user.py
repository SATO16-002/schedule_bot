# -*- coding: utf-8 -*-
"""
app/handlers/user.py — публичные команды для всех: /start, /help, /today, /tomorrow.

Работают и в личке с ботом, и в группах (команды вида /today@MyBot тоже
ловятся — aiogram сам разберёт упоминание бота).
"""
from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.database import db
from app.utils.schedule_utils import DAY_NAMES, format_schedule

# Собственный роутер — подключается в bot.py через dp.include_router()
router = Router(name="user")

HELP_TEXT = (
    "🤖 <b>Бот расписания</b>\n\n"
    "<b>Доступные команды:</b>\n"
    "/today — расписание на сегодня\n"
    "/tomorrow — расписание на завтра\n"
    "/help — справка\n\n"
    "<b>Команды администратора:</b>\n"
    "/set_time 7:30 — время ежедневной рассылки\n"
    "/set_chat -100xxx [topic_id] — чат/тема для рассылки\n"
    "/add_lesson пн 1 Математика — добавить/изменить урок\n"
    "/del_lesson пн 1 — удалить урок\n"
    "/show_settings — текущие настройки\n"
    "/send_now — тестовая рассылка прямо сейчас"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие при первом запуске/в лобби бота."""
    await message.answer(
        "👋 Привет! Я бот школьного расписания.\n"
        "Каждое утро буду присылать уроки в назначенный чат.\n\n"
        f"{HELP_TEXT}",
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Справка по командам."""
    await message.answer(HELP_TEXT)


async def _answer_day(message: Message, day_of_week: int, caption: str) -> None:
    """Общий код для /today и /tomorrow: читаем уроки из БД и отвечаем."""
    lessons = await db.get_lessons(day_of_week)
    text = format_schedule(day_of_week, lessons)
    await message.answer(f"{caption} ({DAY_NAMES[day_of_week]}):\n\n{text}")


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """Расписание на сегодняшний день (с учётом настроенного часового пояса)."""
    # Дату берём в таймзоне рассылки, чтобы «сегодня» совпадало с логикой scheduler
    settings = await db.get_settings()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(settings.timezone))
    except Exception:
        now = datetime.now()
    await _answer_day(message, now.weekday(), "📅 Сегодня")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    """Расписание на завтрашний день."""
    settings = await db.get_settings()
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(settings.timezone))
    except Exception:
        now = datetime.now()
    tomorrow_dow = (now.weekday() + 1) % 7
    await _answer_day(message, tomorrow_dow, "📅 Завтра")
