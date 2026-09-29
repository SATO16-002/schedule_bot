# -*- coding: utf-8 -*-
"""
app/config/loader.py — загрузка конфигурации из .env (python-dotenv).

Здесь собираются все «настройки окружения»: токен, ID админов,
часовой пояс и путь к базе данных. Приложение не должно нигде
больше читать os.environ напрямую.
"""
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Загружаем переменные из файла .env в рабочем каталоге (если он существует)
load_dotenv()


@dataclass(frozen=True)
class Config:
    """Неизменяемые настройки приложения."""
    bot_token: str                          # Токен Telegram-бота
    admin_ids: tuple[int, ...]              # Кортеж ID администраторов
    tz: ZoneInfo                            # Часовой пояс рассылки (по умолчанию МСК)
    database_path: str                      # Путь к файлу SQLite


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    """Превращает строку '111,222' в кортеж int. Пустые/битые значения игнорируются."""
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                # Не числовой фрагмент — пропускаем, но это видно в логах запуска
                continue
    return tuple(ids)


def load_config() -> Config:
    """Читает .env / переменные окружения и возвращает готовый Config.

    При отсутствии обязательных переменных — падаем сразу и понятно,
    а не в момент запуска long polling.
    """
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Переменная BOT_TOKEN не задана. "
            "Скопируйте .env.example в .env и укажите токен бота."
        )

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

    # Часовой пояс по умолчанию — Москва. Можно переопределить через TIMEZONE в .env
    tz_name = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:
        raise RuntimeError(
            f"Некорректный часовой пояс '{tz_name}' в переменной TIMEZONE: {exc}"
        ) from exc

    db_path = os.getenv("DATABASE_PATH", "schedule.db").strip() or "schedule.db"

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        tz=tz,
        database_path=db_path,
    )
