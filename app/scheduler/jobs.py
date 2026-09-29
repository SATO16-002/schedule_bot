# -*- coding: utf-8 -*-
"""
app/scheduler/jobs.py — планировщик APScheduler и сама задача рассылки.

Как это работает:
  1. AsyncIOScheduler запускается внутри основного event loop (без потоков).
  2. Cron-trigger job «daily_broadcast» срабатывает КАЖДУЮ МИНУТУ.
     Это не баг, а страховка: если бот лежал во время планового часа
     (упал сервер, рестарт деплоя), job всё равно «догонит» рассылку
     в ближайшую минуту после восстановления.
  3. Реальная проверка времени и защита от дублей — внутри задачи:
       - сравниваем текущие час:минуту с настройками из БД;
       - сравниваем settings.last_sent_date с сегодняшней датой —
         если сегодня уже отправляли, выходим (защита при перезапуске);
     Всё остальное — мгновенный no-op, нагрузка на CPU/БД нулевая.
  4. Ошибки Telegram API (нет бота в чате, нет прав, flood) только
     логируются — планировщик и бот продолжают работать.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import db
from app.utils.schedule_utils import format_schedule

logger = logging.getLogger(__name__)

JOB_ID = "daily_broadcast"

# Глобальные ссылки, которые задаёт init_scheduler()
_bot: Bot | None = None
_tz: ZoneInfo | None = None
_scheduler: AsyncIOScheduler | None = None


async def run_daily_broadcast() -> None:
    """Тело задачи: вызывается каждую минуту, шлёт расписание по условиям."""
    if _bot is None or _tz is None:
        return  # планировщик ещё не инициализирован — молча выходим

    now = datetime.now(_tz)
    settings = await db.get_settings()

    # --- Шаг 1. Настало ли плановое время? -------------------------------
    # Job тикает раз в минуту начиная с часа рассылки; сравниваем точные
    # час:минуту, чтобы не отправить раньше времени.
    if (now.hour, now.minute) < (settings.send_hour, settings.send_minute):
        return  # ещё не время — дешёвый выход без обращения к Telegram
    if now.hour != settings.send_hour:
        return  # час уже прошёл (например, рестарт на следующий день) — ждём завтра

    # --- Шаг 2. Защита от дублей (критично при перезапуске бота!) --------
    today_iso = now.date().isoformat()
    if settings.last_sent_date == today_iso:
        return  # сегодня уже отправляли — ничего не делаем

    # --- Шаг 3. Есть ли куда отправлять? ----------------------------------
    if settings.chat_id is None:
        logger.warning("Рассылка: чат не задан (используйте /set_chat), пропускаю.")
        return

    # --- Шаг 4. Формируем текст и отправляем -------------------------------
    lessons = await db.get_lessons(now.weekday())
    text = format_schedule(now.weekday(), lessons)

    try:
        await _bot.send_message(
            chat_id=settings.chat_id,
            text=text,
            message_thread_id=settings.topic_id,  # тема форума или None
            parse_mode="HTML",
        )
    except TelegramForbiddenError:
        # Бота удалили из чата / он заблокирован — пишем подробно, но НЕ падаем.
        # last_sent_date НЕ ставим: если админ вернёт бота в тот же день,
        # следующая минутная тик-проверка успешно дошлёт расписание.
        logger.error(
            "Рассылка: нет доступа к чату %s (бот удалён или заблокирован). "
            "Проверьте права бота в чате/теме.",
            settings.chat_id,
        )
        return
    except TelegramAPIError as exc:
        # Любая другая ошибка Telegram API (flood, таймаут, битый topic_id)
        logger.error("Рассылка: ошибка Telegram API при отправке в %s: %s",
                     settings.chat_id, exc)
        return
    except Exception:
        # Страховка от совсем неожиданных ошибок — планировщик не должен умирать
        logger.exception("Рассылка: непредвиденная ошибка")
        return

    # --- Шаг 5. Успех — ставим флаг last_sent_date -------------------------
    await db.set_last_sent_date(now.date())
    logger.info("Рассылка: расписание на %s (%s) отправлено в чат %s.",
                today_iso, now.strftime("%H:%M"), settings.chat_id)


async def send_schedule_now(force: bool = False) -> tuple[bool, str]:
    """Ручная отправка (команда /send_now). Возвращает (ok, пояснение)."""
    if _bot is None:
        return False, "Планировщик не инициализирован."
    settings = await db.get_settings()
    if settings.chat_id is None:
        return False, "Чат для рассылки не задан — используйте /set_chat."

    now = datetime.now(_tz) if _tz else datetime.now()
    lessons = await db.get_lessons(now.weekday())
    text = format_schedule(now.weekday(), lessons)
    try:
        await _bot.send_message(
            chat_id=settings.chat_id,
            text=text,
            message_thread_id=settings.topic_id,
            parse_mode="HTML",
        )
    except TelegramAPIError as exc:
        logger.error("/send_now: ошибка отправки: %s", exc)
        return False, f"Ошибка Telegram API: {exc}. Проверьте, что бот в чате и есть права."
    return True, "Расписание отправлено (флаг last_sent_date не изменён)."


def reschedule_daily_job() -> None:
    """Пересоздаёт job с актуальным часом из БД.

    Вызывается из /set_time, чтобы новый график действовал сразу,
    без перезапуска процесса. Синхронная обёртка над асинхронной
    перестановкой — планировщик и БД живут в одном event loop.
    """
    if _scheduler is None or not _scheduler.running:
        return  # планировщик ещё не стартовал — job поставится при старте

    import asyncio

    async def _apply() -> None:
        s = await db.get_settings()
        trigger = CronTrigger(minute="*", hour=str(s.send_hour), timezone=s.timezone)
        _scheduler.reschedule_job(JOB_ID, trigger=trigger)
        logger.info("Планировщик: job переставлен на час %02d (%s).",
                    s.send_hour, s.timezone)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_apply())


def init_scheduler(bot: Bot, tz: ZoneInfo) -> AsyncIOScheduler:
    """Создаёт планировщик (без старта). Вызывается один раз из bot.py."""
    global _bot, _tz, _scheduler
    _bot, _tz = bot, tz
    _scheduler = AsyncIOScheduler(timezone=tz)
    return _scheduler


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Старт планировщика + постановка ежедневного job по настройкам из БД."""
    s = await db.get_settings()
    # Cron «каждую минуту часа рассылки»: если процесс лежал в нужный момент,
    # ближайший тик после восстановления дошлёт расписание (см. run_daily_broadcast).
    trigger = CronTrigger(minute="*", hour=str(s.send_hour), timezone=s.timezone)
    scheduler.add_job(
        run_daily_broadcast,
        trigger=trigger,
        id=JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,  # догонять пропущенные тики в течение часа
        coalesce=True,            # пачку пропусков схлопнуть в один запуск
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Планировщик запущен: рассылка в %02d:%02d, окно тиков — час %02d (%s).",
                s.send_hour, s.send_minute, s.send_hour, s.timezone)
