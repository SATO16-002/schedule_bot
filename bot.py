# -*- coding: utf-8 -*-
"""
bot.py — точка входа production-версии бота расписания.

Порядок запуска:
  1. load_config()   — читаем .env (токен, админы, таймзона, путь к БД);
  2. db.init_db + create_tables — инициализация SQLite (идемпотентно);
  3. Bot/Dispatcher + подключение роутеров (user, admin);
  4. set_my_commands — меню команд в Telegram UI;
  5. init_scheduler + start_scheduler — APScheduler вместо while True;
  6. dp.start_polling — long polling с корректным shutdown (Ctrl+C / SIGTERM).

Запуск:  python bot.py
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

from app.config.loader import load_config
from app.database import db
from app.handlers import user as user_handlers
from app.handlers.admin import build_admin_router
from app.scheduler.jobs import init_scheduler, start_scheduler

# Логирование: INFO для нашего кода, WARNING для шумных библиотек
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger("bot")


async def on_startup(bot: Bot) -> None:
    """Хук запуска: регистрируем меню команд в интерфейсе Telegram."""
    await bot.set_my_commands(
        [
            BotCommand(command="/start", description="Приветствие"),
            BotCommand(command="/help", description="Справка по командам"),
            BotCommand(command="/today", description="Расписание на сегодня"),
            BotCommand(command="/tomorrow", description="Расписание на завтра"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )


async def main() -> None:
    # 1. Конфигурация -------------------------------------------------------
    config = load_config()
    logger.info(
        "Конфигурация загружена. Админов: %d, таймзона: %s, БД: %s",
        len(config.admin_ids), config.tz.key, config.database_path,
    )

    # 2. База данных --------------------------------------------------------
    db.init_db(config.database_path)
    await db.create_tables()
    logger.info("База данных готова (таблицы settings/lessons созданы при необходимости).")

    # 3. Bot + Dispatcher + роутеры -----------------------------------------
    # parse_mode=HTML задаём один раз глобально — не забываем ни в одном ответе
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(user_handlers.router)          # публичные команды
    dp.include_router(build_admin_router(config))    # админские команды + отказ не-админам
    dp.startup.register(lambda: on_startup(bot))     # меню команд при старте

    # 4. Планировщик (APScheduler вместо while True + sleep) -----------------
    scheduler = init_scheduler(bot, config.tz)
    await start_scheduler(scheduler)

    # 5. Long polling; при остановке — аккуратно гасим планировщик и сессию bot
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Бот остановлен, ресурсы освобождены.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        # Ctrl+C в консоли — штатное завершение
        logger.info("Получен сигнал остановки, выходим.")
