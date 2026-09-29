import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ТОКЕН БОТА (получи у @BotFather в Telegram)
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"

# ID ТВОЕГО ЧАТА ИЛИ ТЕМЫ (куда отправлять расписание)
# Чтобы узнать ID, перешли любое сообщение из нужного чата боту @ShowJsonBot
CHAT_ID = -1001234567890 
TOPIC_ID = None  # Если отправляешь в конкретную тему группы, укажи её ID (message_thread_id)

# РАСПИСАНИЕ УРОКОВ
SCHEDULE = {
    0: "📚 Понедельник:\n1. Математика\n2. Русский язык\n3. Физика\n4. История",
    1: "📚 Вторник:\n1. Химия\n2. Биология\n3. Литература\n4. Английский язык",
    2: "📚 Среда:\n1. География\n2. Математика\n3. Физкультура\n4. Информатика",
    3: "📚 Четверг:\n1. Русский язык\n2. Физика\n3. Обществознание\n4. Геометрия",
    4: "📚 Пятница:\n1. Английский язык\n2. Литература\n3. Биология\n4. Музыка",
    5: "🎉 Суббота:\nВыходной! Отдыхай! 🙌",
    6: "🎉 Воскресенье:\nВыходной! Набирайся сил перед неделей! 🚀"
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Команда /start для проверки работы бота
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я бот расписания. Я буду автоматически присылать уроки каждый день в 06:00.")

# Функция автоматической отправки расписания
async def schedule_sender():
    while True:
        now = datetime.now()
        
        # Проверяем, наступило ли 6 часов утра
        if now.hour == 6 and now.minute == 0:
            weekday = now.weekday()  # Получаем текущий день недели (0 - Пн, 6 - Вс)
            text = SCHEDULE.get(weekday, "Расписание не найдено.")
            
            try:
                # Отправляем сообщение (с учетом возможной темы в группе)
                await bot.send_message(chat_id=CHAT_ID, text=text, message_thread_id=TOPIC_ID)
                logging.info(f"Расписание на день {weekday} успешно отправлено.")
            except Exception as e:
                logging.error(f"Ошибка при отправке: {e}")
                
            # Ждем минуту, чтобы бот не отправил сообщение несколько раз за одну минуту
            await asyncio.sleep(60)
            
        # Спим 30 секунд до следующей проверки времени
        await asyncio.sleep(30)

async def main():
    # Запускаем фоновую задачу для проверки времени и отправки расписания
    asyncio.create_task(schedule_sender())
    # Запускаем чтение сообщений (команд)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
