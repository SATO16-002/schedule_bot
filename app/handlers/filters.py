# -*- coding: utf-8 -*-
"""
app/handlers/filters.py — собственные фильтры aiogram 3.x.

IsAdmin: пропускает апдейт дальше только если user.id есть в ADMIN_IDS
из .env. Используется как «магия» в начале админских хендлеров —
обычные пользователи получают отказ через отдельный fallback-хендлер.
"""
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.config.loader import Config


class IsAdmin(BaseFilter):
    """Фильтр: автор сообщения — администратор из конфигурации."""

    def __init__(self, config: Config) -> None:
        self.config = config

    async def __call__(self, message: Message) -> bool:
        # У анонимных админов каналов user может отсутствовать — считаем не админом
        return bool(message.from_user) and message.from_user.id in self.config.admin_ids
