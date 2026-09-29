# 📚 Бот расписания (aiogram 3.x + APScheduler + SQLite)

Production-ready Telegram-бот, который ежедневно рассылает расписание уроков
в заданный чат/тему форума и отвечает на команды пользователей.

## Структура проекта

```
├── bot.py                  # Точка входа: Bot, Dispatcher, роутеры, запуск планировщика
├── requirements.txt        # Зависимости
├── .env.example            # Шаблон переменных окружения (скопируйте в .env)
├── old/schedule_bot_legacy.py  # Старый прототип (архив, не используется)
└── app/
    ├── config/
    │   └── loader.py       # Чтение BOT_TOKEN / ADMIN_IDS / TIMEZONE / DATABASE_PATH
    ├── database/
    │   └── db.py           # aiosqlite: схема (settings, lessons), CRUD-функции
    ├── handlers/
    │   ├── filters.py      # IsAdmin — доступ только по ADMIN_IDS
    │   ├── user.py         # /start, /help, /today, /tomorrow (роутер "user")
    │   └── admin.py        # /set_time, /set_chat, /add_lesson, /del_lesson,
    │                       # /show_settings, /send_now + вежливый отказ не-админам
    ├── scheduler/
    │   └── jobs.py         # APScheduler: ежедневный job, last_sent_date, обработка ошибок
    └── utils/
        └── schedule_utils.py  # Дни недели, парсинг, форматирование HTML-сообщения
```

## Ключевые решения

- **APScheduler вместо `while True`** — cron-job тикает раз в минуту *внутри часа
  рассылки*: если бот лежал в нужный момент, ближайший тик после восстановления
  «догонит» отправку (`misfire_grace_time`, `coalesce`).
- **Защита от дублей** — флаг `last_sent_date` в таблице `settings`: перед отправкой
  сравнивается с сегодняшней датой в таймзоне рассылки. Перезапуск процесса
  не приводит к повторной рассылке.
- **Ошибки доставки не крашат бота** — `TelegramForbiddenError` (бота удалили из чата)
  и любые `TelegramAPIError` только логируются; при ошибке флаг `last_sent_date`
  НЕ выставляется, поэтому после починки прав бот дошлёт расписание в тот же день.
- **Часовые пояса** — `zoneinfo`, по умолчанию `Europe/Moscow`, переопределяется
  через `TIMEZONE` в `.env`.
- **HTML parse-mode** задан один раз в `DefaultBotProperties`.

## Развёртывание

1. Python 3.10+ (используется `zoneinfo`).
2. Установить зависимости:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Создать бота у [@BotFather](https://t.me/BotFather), скопировать токен.
4. Скопировать `.env.example` → `.env`, заполнить `BOT_TOKEN`, `ADMIN_IDS`
   (свой ID — у @userinfobot).
5. Добавить бота в целевой чат/группу (для тем — включить Topics и дать права
   на отправку сообщений).
6. Запуск:
   ```bash
   python bot.py
   ```

### Первый шаг после запуска (в личке или в чате)

```
/add_lesson пн 1 Математика
/set_chat -1001234567890 42     # или просто /set_chat из нужного чата/темы
/set_time 6:30
/show_settings
/send_now                        # проверка доставки
```

## Автозапуск в бою (systemd)

`/etc/systemd/system/schedule-bot.service`:

```ini
[Unit]
Description=Schedule Telegram Bot
After=network-online.target

[Service]
WorkingDirectory=/opt/schedule-bot
ExecStart=/opt/schedule-bot/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now schedule-bot
journalctl -u schedule-bot -f
```

Файл базы `schedule.db` лежит рядом с `bot.py` (путь настраивается через
`DATABASE_PATH`) — не забудьте включать его в бэкапы.
