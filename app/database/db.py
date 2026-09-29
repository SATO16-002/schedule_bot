# -*- coding: utf-8 -*-
"""
app/database/db.py — асинхронный слой работы с SQLite (aiosqlite).

Схема:
  settings  — одна строка с id=1: время рассылки, часовой пояс, чат/топика,
              флаг last_sent_date (защита от дублей при перезапуске);
  lessons   — уроки: (day_of_week, lesson_number) уникальны, повторный
              /add_lesson обновляет существующую запись (UPSERT).

Все функции принимают путь к БД (или используют глобальный, заданный
через init_db()) и работают через context manager aiosqlite.connect,
чтобы не держать соединение открытым между операциями.
"""
from __future__ import annotations

import aiosqlite
from dataclasses import dataclass
from datetime import date

# Глобальный путь к базе, задаётся один раз при старте приложения
_DB_PATH: str = "schedule.db"


def init_db(path: str) -> None:
    """Запоминает путь к файлу базы данных (вызывается из bot.py)."""
    global _DB_PATH
    _DB_PATH = path


# ---------------------------------------------------------------------------
# Инициализация схемы
# ---------------------------------------------------------------------------

_SCHEMA = """
-- Настройки бота: всегда ровно одна строка с id = 1
CREATE TABLE IF NOT EXISTS settings (
    id                INTEGER PRIMARY KEY CHECK (id = 1), -- синглтон-строка
    send_hour         INTEGER NOT NULL DEFAULT 6,         -- час рассылки (0-23)
    send_minute       INTEGER NOT NULL DEFAULT 0,         -- минута рассылки (0-59)
    timezone          TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    chat_id           INTEGER,                            -- куда слать расписание
    topic_id          INTEGER,                            -- message_thread_id (forum тема) или NULL
    last_sent_date    TEXT                                -- 'ГГГГ-ММ-ДД' последней успешной рассылки
);

-- Уроки расписания
CREATE TABLE IF NOT EXISTS lessons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week  INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Пн ... 6=Вс
    lesson_number INTEGER NOT NULL CHECK (lesson_number >= 1),
    title        TEXT    NOT NULL,
    UNIQUE (day_of_week, lesson_number)                 -- один урок на номер в день недели
);

CREATE INDEX IF NOT EXISTS idx_lessons_day ON lessons (day_of_week);
"""


async def create_tables() -> None:
    """Создаёт таблицы и гарантийную строку настроек (idempotent — можно звать каждый запуск)."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(_SCHEMA)
        # INSERT OR IGNORE: строка настроек существует всегда,
        # повторный запуск ничего не перетирает.
        await db.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
        await db.commit()


# ---------------------------------------------------------------------------
# Dataclass-модели (для типобезопасности)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    send_hour: int
    send_minute: int
    timezone: str
    chat_id: int | None
    topic_id: int | None
    last_sent_date: str | None  # ISO-дата 'ГГГГ-ММ-ДД' либо None


@dataclass(frozen=True)
class Lesson:
    day_of_week: int
    lesson_number: int
    title: str


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

async def get_settings() -> Settings:
    """Возвращает текущие настройки (строка id=1 гарантирована create_tables)."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id = 1") as cur:
            row = await cur.fetchone()
        return Settings(
            send_hour=row["send_hour"],
            send_minute=row["send_minute"],
            timezone=row["timezone"],
            chat_id=row["chat_id"],
            topic_id=row["topic_id"],
            last_sent_date=row["last_sent_date"],
        )


async def set_send_time(hour: int, minute: int) -> None:
    """Обновляет время ежедневной рассылки."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE settings SET send_hour = ?, send_minute = ? WHERE id = 1",
            (hour, minute),
        )
        await db.commit()


async def set_target_chat(chat_id: int, topic_id: int | None) -> None:
    """Обновляет целевой чат и (опционально) тему форума."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE settings SET chat_id = ?, topic_id = ? WHERE id = 1",
            (chat_id, topic_id),
        )
        await db.commit()


async def get_last_sent_date() -> str | None:
    """Дата (ISO) последней успешной рассылки либо None, если ещё не отправляли."""
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute("SELECT last_sent_date FROM settings WHERE id = 1") as cur:
            row = await cur.fetchone()
        return row[0] if row else None


async def set_last_sent_date(sent_date: date) -> None:
    """Ставит флаг «рассылка сегодня уже была» — защита от дублей при рестарте."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE settings SET last_sent_date = ? WHERE id = 1",
            (sent_date.isoformat(),),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Уроки
# ---------------------------------------------------------------------------

async def upsert_lesson(day_of_week: int, lesson_number: int, title: str) -> None:
    """Добавляет урок или обновляет его название, если (день, номер) уже есть."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO lessons (day_of_week, lesson_number, title)
            VALUES (?, ?, ?)
            ON CONFLICT (day_of_week, lesson_number)
            DO UPDATE SET title = excluded.title
            """,
            (day_of_week, lesson_number, title),
        )
        await db.commit()


async def delete_lesson(day_of_week: int, lesson_number: int) -> bool:
    """Удаляет урок. Возвращает True, если что-то было удалено."""
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM lessons WHERE day_of_week = ? AND lesson_number = ?",
            (day_of_week, lesson_number),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_lessons(day_of_week: int) -> list[Lesson]:
    """Список уроков на указанный день недели, отсортирован по номеру."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT day_of_week, lesson_number, title FROM lessons "
            "WHERE day_of_week = ? ORDER BY lesson_number",
            (day_of_week,),
        ) as cur:
            rows = await cur.fetchall()
        return [Lesson(r["day_of_week"], r["lesson_number"], r["title"]) for r in rows]
